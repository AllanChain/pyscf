#!/usr/bin/env python
# Copyright 2014-2020 The PySCF Developers. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Authors: Xing Zhang <zhangxing.nju@gmail.com>
#

import numpy as np
from pyscf import __config__
from pyscf import lib
from pyscf.gto import mole
from pyscf.pbc.symm import space_group as spg
from functools import reduce

SYMPREC = getattr(__config__, 'pbc_symm_space_group_symprec', 1e-6) #this has the unit of length

def search_point_group_ops(cell, tol=SYMPREC):
    a = cell.lattice_vectors()
    G = np.dot(a, a.T)
    pbc_axis = np.array([1,1,1], dtype=bool)
    if cell.dimension < 3:
        pbc_axis[cell.dimension:] = False

    a_norm = np.sqrt(np.diag(G))
    a_angle = np.arccos(G / np.outer(a_norm, a_norm))
    tol2 = tol**2

    rotations = []
    for op in lib.cartesian_prod([[1,0,-1],]*9):
        W = np.asarray(op, dtype=np.int32).reshape(3,3) 
        G_tilde = reduce(np.dot, (W.T, G, W))

        #check change of metric
        a_tilde_norm = np.sqrt(np.diag(G_tilde))
        length_error = np.abs(a_norm - a_tilde_norm)
        if (length_error > tol).any():
            continue
        tmp = (a_norm + a_tilde_norm)
        a_tilde_angle = np.arccos(G_tilde / np.outer(a_tilde_norm, a_tilde_norm))
        angle_error = np.sin(a_angle - a_tilde_angle) **2 * np.outer(tmp,tmp) / 4
        if (angle_error > tol2).any():
            continue

        #check if rotation inverts non-periodic axes
        if not (W[np.diag(~pbc_axis)] == 1).all():
            continue

        #check if rotation swaps periodic and non-periodic axes
        pbc_axis2 = np.logical_and.outer(pbc_axis, pbc_axis)       
        if W[~(pbc_axis2 | np.eye(3, dtype=bool))].any():
            continue

        rotations.append(W)

    rotations = np.asarray(rotations)
    return rotations

def search_space_group_ops(cell, rotations=None, tol=SYMPREC):
    if rotations is None: rotations = search_point_group_ops(cell, tol=tol)
    a = cell.lattice_vectors()
    coords = cell.get_scaled_positions()
    atmgrp = mole.atom_types(cell._atom, magmom=cell.magmom)

    def test_trans(R, t):
        for atm, idx in atmgrp.items():
            x = coords[idx]
            xt = np.dot(x, R.T) + t
            x_xt = np.concatenate((x,xt))
            x_xt = np.mod(x_xt, 1)
            x_xt = np.round(x_xt, -np.log10(tol).astype(int))
            x_xt = np.mod(x_xt, 1)
            sorted_idx = np.lexsort(x_xt.T)
            x_xt = x_xt[sorted_idx]
            diff = np.dot(x_xt[::2] - x_xt[1::2], a)
            if (np.abs(diff) > tol).any():
                return False
        return True

    grp_len = [len(v) for v in atmgrp.values()]
    atm = [k for k in atmgrp.keys() if len(atmgrp[k]) == min(grp_len)][0]
    x = coords[atmgrp[atm]]
    ops = []
    for rot in rotations:
        w = x - np.dot(x[0], rot.T)
        w = np.mod(w, 1)
        w = np.round(w, -np.log10(tol).astype(int))
        w = np.mod(w, 1)
        for trans in w:
            if test_trans(rot, trans):
                ops.append(spg.SpaceGroup_element(rot, trans))
    return ops

def get_crystal_class(cell, ops=None, tol=SYMPREC):
    if ops is None: ops = search_space_group_ops(cell, tol=tol)
    rotations = []
    for op in ops:
        rotations.append(op.rot)
    rotations = np.unique(np.asarray(rotations), axis=0)

    maps =  {-6 : 0,
             -4 : 1,
             -3 : 2,
             -2 : 3,
             -1 : 4,
              1 : 5,
              2 : 6,
              3 : 7,
              4 : 8,
              6 : 9}
    table = [0,] * 10
    for rot in rotations:
        trace = np.trace(rot)
        det = np.linalg.det(rot)
        if trace == 3:
            assert(det == 1)
            table[maps[1]] += 1
        elif trace == -3:
            assert(det == -1)
            table[maps[-1]] += 1
        elif trace == 2:
            assert(det == 1)
            table[maps[6]] += 1
        elif trace == -2:
            assert(det == -1)
            table[maps[-6]] += 1
        elif trace == 0:
            if det == 1:
                table[maps[3]] += 1
            elif det == -1:
                table[maps[-3]] += 1
        elif trace == 1:
            if det == 1:
                table[maps[4]] += 1
            elif det == -1:
                table[maps[-2]] += 1
        elif trace == -1:
            if det == 1:
                table[maps[2]] += 1
            elif det == -1:
                table[maps[-4]] += 1
        else:
            raise RuntimeError("Input rotation matrix is wrong: %s" % rot)

    from pyscf.pbc.symm.tables import CrystalClass, LaueClass
    laue_class = None
    crystal_class = None
    for k, v in CrystalClass.items():
        count = 0
        for i in range(10):
            if table[i] == v[i]: count += 1
        if count == 10:
            crystal_class = k
            break
    for k, v in LaueClass.items():
        if crystal_class in v:
            laue_class = k
            break
    if crystal_class is None or laue_class is None:
        raise RuntimeError("Unable to determine crystal class.")
    return crystal_class, laue_class

if __name__ == "__main__":
    from pyscf.pbc import gto
    cell = gto.Cell()
    cell.atom = """
        Si  0.0 0.0 0.0
        Si  1.3467560987 1.3467560987 1.3467560987
    """
    cell.a = [[0.0, 2.6935121974, 2.6935121974], 
              [2.6935121974, 0.0, 2.6935121974], 
              [2.6935121974, 2.6935121974, 0.0]]
    cell.build()

    ops = search_space_group_ops(cell)
    print(get_crystal_class(cell, ops=ops)[0])
