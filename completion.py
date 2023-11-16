from __future__ import print_function
from __future__ import absolute_import
import math
import sys
from string import ascii_letters

import iotbx
from mmtbx.monomer_library import server
from scitbx import matrix
from scitbx.math import dihedral_angle
from libtbx.utils import Sorry
from functools import cmp_to_key

from iotbx.pdb import amino_acid_codes as aac

mon_lib_server = server.server()
get_class = iotbx.pdb.common_residue_names_get_class

from qrefine.utils import hierarchy_utils
from mmtbx.hydrogens.specialised_hydrogen_atoms import conditional_add_cys_hg_to_atom_group
from mmtbx.hydrogens.specialised_hydrogen_atoms import conditional_remove_cys_hg_to_atom_group
from mmtbx.ligands.hierarchy_utils import _add_atom_to_chain
from mmtbx.ligands.hierarchy_utils import is_hierarchy_altloc_consistent
from mmtbx.ligands.ready_set_utils import add_n_terminal_hydrogens_to_residue_group
from mmtbx.ligands.ready_set_utils import add_c_terminal_oxygens_to_residue_group
from mmtbx.ligands.ready_set_utils import generate_protein_fragments

def d_squared(xyz1, xyz2):
  d2 = 0
  for i in range(3):
    d2 += (xyz2[i]-xyz1[i])**2
  return d2

def get_bond_vector(a1,a2,unit=False):
  vector = []
  l = 0
  for i in range(3):
    vector.append(a1.xyz[i]-a2.xyz[i])
    l+=vector[i]**2
  if unit:
    l=math.sqrt(l)
    for i in range(3):
      vector[i] /= l
  return tuple(vector)

def construct_xyz(ba, bv,
                  aa, av,
                  da, dv,
                  period=3,
                  ):
  assert ba is not None
  assert aa is not None
  assert da is not None
  rn = matrix.col(ba.xyz)
  rca = matrix.col(aa.xyz)
  rc = matrix.col(da.xyz)
  rcca = rc -rca

  e0 = (rn - rca).normalize()
  e1 = (rcca - (rcca.dot(e0))*e0).normalize()
  e2 = e0.cross(e1)

  pi = math.pi
  alpha = math.radians(av)
  phi = math.radians(dv)

  rh_list = []
  for n in range(0, period):
    rh = rn + bv * (math.sin(alpha)*(math.cos(phi + n*2*pi/period)*e1 +
                                     math.sin(phi + n*2*pi/period)*e2) -
                    math.cos(alpha)*e0)
    rh_list.append(rh)
  return rh_list

def get_atoms_by_names(ag, l=None, all_or_nothing=True):
  assert l
  assert 0
  rc = []
  for name in l:
    atom = ag.get_atom(name)
    rc.append(atom)
  if len(l)!=len(filter(None, rc)): return None
  return rc

def _add_hydrogens_to_atom_group_using_bad(ag,
                                           atom_name,
                                           atom_element,
                                           bond_atom,
                                           angle_atom,
                                           dihedral_atom,
                                           bond_length,
                                           angle,
                                           dihedral,
                                           append_to_end_of_model=False,
                                           ):
  rc = []
  if ag.get_atom(atom_name.strip()): return []
  if type(bond_atom)==type(''):
    ba = ag.get_atom(bond_atom.strip())
    #print bond_atom,ba.quote()
    if ba is None: return
  else: ba = bond_atom
  if type(angle_atom)==type(''):
    aa = ag.get_atom(angle_atom.strip())
    #print angle_atom,aa.quote()
    if aa is None: return
  else: aa = angle_atom
  if type(dihedral_atom)==type(''):
    da = ag.get_atom(dihedral_atom.strip())
    #print dihedral_atom, da.quote()
    if da is None: return
  else: da = dihedral_atom
  ro2 = construct_xyz(ba, bond_length,
                      aa, angle,
                      da, dihedral,
                      period=1,
                     )
  atom = iotbx.pdb.hierarchy.atom()
  atom.name = atom_name
  atom.element = atom_element
  atom.occ = ba.occ
  atom.b = ba.b
  # altloc???
  atom.hetero = ba.hetero
  atom.segid = ' '*4
  atom.xyz = ro2[0]
  if append_to_end_of_model:
    chain = _add_atom_to_chain(atom,
                               ag,
                               icode=ba.parent().parent().icode)
    rc.append(chain)
  else:
    ag.append_atom(atom)
  return rc

def add_cys_hg_to_atom_group(ag,
                             append_to_end_of_model=False,
                            ):
  #
  # do we need ANISOU
  #
  proton_name=proton_element='H'
  if is_perdeuterated(ag):
    proton_name=proton_element='D'
  rc = _add_hydrogens_to_atom_group_using_bad(
    ag,
    ' HG ',
    'H',
    'SG',
    'CB',
    'CA',
    1.2,
    120.,
    160.,
    append_to_end_of_model=append_to_end_of_model,
   )
  return rc

def add_cys_hg_to_residue_group(rg,
                                append_to_end_of_model=False,
                               ):
  rc=[]
  for ag in rg.atom_groups():
    if ag.resname not in ['CYS']: continue
    rc += add_cys_hg_to_atom_group(
      ag,
      append_to_end_of_model=append_to_end_of_model,
    )
  return rc

def remove_cys_hg_from_residue_group(rg):
  proton_element, proton_name = get_proton_info(rg)
  for ag in rg.atom_groups():
    if ag.resname not in ['CYS']: continue
    for atom in ag.atoms():
      if atom.name==' %sG ' % proton_element:
        ag.remove_atom(atom)
        break

def iterate_over_threes(hierarchy,
                        geometry_restraints_manager,
                        use_capping_hydrogens=False,
                        append_to_end_of_model=False,
                        verbose=False,
                        ):
  atoms = hierarchy.atoms()
  ###
  def get_residue_group(residue):
    for atom in residue.atoms():
      atom = atoms[atom.i_seq]
      break
    return atom.parent().parent()
  ###
  additional_hydrogens=hierarchy_utils.smart_add_atoms()
  for three in generate_protein_fragments(
    hierarchy,
    geometry_restraints_manager,
    backbone_only=False,
    use_capping_hydrogens=use_capping_hydrogens,
  ):
    if verbose: print(three)
    if not len(three): continue
    ptr=0
    assert three.are_linked()
    if use_capping_hydrogens:
      for i in range(len(three)):
        rg = get_residue_group(three[i])
        rc = conditional_add_cys_hg_to_atom_group(
          geometry_restraints_manager,
          rg,
          append_to_end_of_model=append_to_end_of_model,
          )
        if rc:
          print('rc1',rc)
          additional_hydrogens.append(rc)
    else:
      for i in range(len(three)):
        rg = get_residue_group(three[i])
        conditional_remove_cys_hg_to_atom_group(geometry_restraints_manager,
                                                rg,
                                                )
    # check if N-term residue - FVA
    n_term_done = False
    if three[0].resname in ['FVA',
                            ]:
      n_term_done = True
      ptr+=1
      assert ptr==1, 'ptr (%d) is not 1' % ptr
    if three.start and not n_term_done:
      ptr+=1
      assert ptr==1, 'ptr (%d) is not 1' % ptr
      rg = get_residue_group(three[0])
      rc = add_n_terminal_hydrogens_to_residue_group(
        rg,
        use_capping_hydrogens=use_capping_hydrogens,
        append_to_end_of_model=append_to_end_of_model,
      )
      if rc: additional_hydrogens.append(rc)
      #hierarchy.reset_i_seq_if_necessary()
    c_term_done = False
    if three[-1].resname in ['ETA',
                             ]:
      c_term_done = True
      ptr-=1
      assert ptr==0, 'ptr (%d) is not 0' % ptr
    if three.end and not c_term_done:
      ptr-=1
      assert ptr==0, 'ptr (%d) is not 0' % ptr
      rg = get_residue_group(three[-1])
      rc = add_c_terminal_oxygens_to_residue_group(
        rg,
        use_capping_hydrogens=use_capping_hydrogens,
        append_to_end_of_model=append_to_end_of_model,
      )
      print(rc)
      if rc: additional_hydrogens.append(rc)
      #hierarchy.reset_i_seq_if_necessary()
    else:
      pass
  return additional_hydrogens

def iterate_using_original(hierarchy,
                           geometry_restraints_manager,
                           original_hierarchy,
                           use_capping_hydrogens=False,
                           append_to_end_of_model=False,
                           ):
  slots=[]
  start=18
  assert len(original_hierarchy.models())==1
  assert len(hierarchy.models())==1
  for chain in original_hierarchy.chains():
    for org in chain.residue_groups():
      protein = True
      for atom_group in org.atom_groups():
        if(get_class(atom_group.resname) not in ["common_amino_acid",
                                                 "modified_amino_acid",
                                               ] and
           atom_group.resname not in aac.three_letter_l_given_three_letter_d):
          protein=False
          break
      if not protein:
        slots.append(False)
        continue
      org_atom1_quote = org.atoms()[0].quote()[start:]
      for rg in hierarchy.residue_groups():
        if rg.atoms()[0].quote()[start:]==org_atom1_quote:
          slots.append(rg)
          break
      else:
        slots.append(0)
    slots.append(None)

  ptr=0
  additional_hydrogens=[]
  for i in range(len(slots)):
    start=False
    end=False
    if slots[i]:
      if i==0: start=True
      elif not slots[i-1]: start=True
      if i==len(slots)-1: end=True
      elif not slots[i+1]: end=True
      # does not work for chain ends
    else: continue
    rg = slots[i]
    conditional_add_cys_hg_to_atom_group(geometry_restraints_manager,
                                         rg,
                                         append_to_end_of_model=append_to_end_of_model)
    if start:
      ptr+=1
      assert ptr==1
      if hierarchy_utils.is_n_terminal_residue(rg):
        rc = None
      else:
        rc = add_n_terminal_hydrogens_to_residue_group(
          rg,
          use_capping_hydrogens=use_capping_hydrogens,
          append_to_end_of_model=append_to_end_of_model,
        )
      if rc: additional_hydrogens.append(rc)
    if end:
      ptr-=1
      assert ptr==0
      rc = add_c_terminal_oxygens_to_residue_group(
        rg,
        use_capping_hydrogens=use_capping_hydrogens,
        append_to_end_of_model=append_to_end_of_model,
      )
      if rc: additional_hydrogens.append(rc)
    else:
      pass
  return additional_hydrogens

def use_electrons_to_add_hdyrogens(hierarchy,
                                   geometry_restraints_manager,
                                   use_capping_hydrogens=False,
                                   append_to_end_of_model=False,
                                   ):
  if not use_capping_hydrogens: return
  from mmtbx.ligands import electrons
  rc=[]
  raw_records = hierarchy_utils.get_raw_records(
    pdb_hierarchy=hierarchy,
    crystal_symmetry=geometry_restraints_manager.crystal_symmetry,
  )
  charges = electrons.run(pdb_filename=None,
                          raw_records=raw_records,
                          return_formal_charges=True,
  )
  charged_atoms = charges.get_charged_atoms()
  remove=[]
  proton_element, proton_name = get_proton_info(hierarchy)
  for atom, electrons in charged_atoms:
    atom_group = atom.parent()
    #if atom_group.resname=='CYS' and atom.name==' SG ':
    #  if electrons==-1 and atom_group.get_atom('HG'):
    #    remove.append(atom_group.get_atom('HG'))
    if atom.element_is_hydrogen() and electrons==1:
      #print 'REMOVING', atom.quote()
      remove.append(atom)
    if get_class(atom.parent().resname) in ['common_amino_acid',
                                            ]:
      continue
    atom = hierarchy.atoms()[atom.i_seq]
    # this does not even work
    rc = _add_hydrogens_to_atom_group_using_bad(
      atom.parent(),
      ' %s1 ' % proton_element,
      proton_element,
      atom.name.strip(),
      'C4',
      'C3',
      1.,
      120.,
      160.,
      append_to_end_of_model=append_to_end_of_model,
    )
  def _atom_i_seq(a1, a2):
    if a1.i_seq<a2.i_seq: return -1
    return 1
  if remove:
    remove.sort(key=cmp_to_key(_atom_i_seq))
    remove.reverse()
    for atom in remove:
      # this is a kludge
      # print(atom,atom.i_seq)
      name = atom.name
      atom = hierarchy.atoms()[atom.i_seq]
      atom_group = atom.parent()
      atom = atom_group.get_atom(name.strip())
      atom_group.remove_atom(atom)
  return rc

def add_terminal_hydrogens(
    hierarchy,
    geometry_restraints_manager,
    add_to_chain_breaks=False,
    use_capping_hydrogens=False,  # instead of terminal H
    append_to_end_of_model=False, # useful for Q|R
    #use_capping_only_on_chain_breaks=False,
    original_hierarchy=None,
    occupancy=1.,
    verbose=False,
    ):
  # add N terminal hydrogens because Reduce only does it to resseq=1
  # needs to be alt.loc. aware for non-quantum-refine
  if original_hierarchy:
    additional_hydrogens = iterate_using_original(
      hierarchy,
      geometry_restraints_manager,
      original_hierarchy,
      use_capping_hydrogens=use_capping_hydrogens,
      append_to_end_of_model=append_to_end_of_model,
      )
  else:
    additional_hydrogens=iterate_over_threes(
      hierarchy,
      geometry_restraints_manager,
      use_capping_hydrogens=use_capping_hydrogens,
      append_to_end_of_model=append_to_end_of_model,
    )

  # add hydrogens to non-protein
  non_protein = False
  for atom_group in hierarchy.atom_groups():
    if get_class(atom_group.resname) not in ['common_amino_acid']:
      non_protein=True
      break
  if non_protein and 0:
    rc = use_electrons_to_add_hdyrogens(
      hierarchy,
      geometry_restraints_manager,
      use_capping_hydrogens=use_capping_hydrogens,
      append_to_end_of_model=append_to_end_of_model,
    )
    if rc: additional_hydrogens += [rc]

  if append_to_end_of_model and additional_hydrogens:
    tmp = []
    for group in additional_hydrogens:
      for chain in group:
        tmp.append(chain)
    _add_atoms_from_chains_to_end_of_hierarchy(hierarchy, tmp)

def _add_atoms_from_chains_to_end_of_hierarchy(hierarchy, chains):
  lookup = {}
  for chain in chains:
    lookup.setdefault(chain.id, [])
    lookup[chain.id].append(chain)
  model = hierarchy.models()[0]
  for i, chain_group in sorted(lookup.items()):
    tc = iotbx.pdb.hierarchy.chain()
    tc.id = i
    for chain in chain_group:
      for rg in chain.residue_groups():
        tc.append_residue_group(rg.detached_copy())
    model.append_chain(tc)

def _add_atoms_from_residue_groups_to_end_of_hierarchy(hierarchy, rgs):
  assert 0
  chains = {}
  for rg in rgs:
    for atom in rg.atoms():
      # this is a bad idea
      cid = atom.tmp
      if cid not in chains:
        chains[cid] = iotbx.pdb.hierarchy.chain()
        chains[cid].id = ascii_letters[cid]
      chains[cid].append_residue_group(rg)
  model = hierarchy.models()[0]
  for i, chain in sorted(chains.items()):
    model.append_chain(chain)

def remove_acid_side_chain_hydrogens(hierarchy):
  from mmtbx.ligands.ready_set_utils import get_proton_info
  proton_element, proton_name = get_proton_info(hierarchy)
  removes = {"GLU" : "%sE2" % proton_element,
             "ASP" : "%sD2" % proton_element,
             }
  for ag in hierarchy.atom_groups():
    r = removes.get(ag.resname, None)
    if r is None: continue
    atom = ag.get_atom(r)
    if atom:
      ag.remove_atom(atom)
  hierarchy.atoms_reset_serial()
  hierarchy.atoms().reset_i_seq()
  return hierarchy

def _eta_peptide_h(hierarchy,
                   geometry_restraints_manager,
                   verbose=False,
                   ):
  proton_element, proton_name = get_proton_info(hierarchy)
  atoms = hierarchy.atoms()
  ###
  def get_residue_group(residue):
    for atom in residue.atoms():
      atom = atoms[atom.i_seq]
      break
    return atom.parent().parent()
  ###
  for three in generate_protein_fragments(
    hierarchy,
    geometry_restraints_manager,
    backbone_only=False,
    #use_capping_hydrogens=use_capping_hydrogens,
    ):
    if len(three)==1: continue
    if three[-1].resname!='ETA': continue
    print(three)
    eta = get_residue_group(three[-1])
    print(dir(eta))
    previous = get_residue_group(three[-2])
    print(previous)
    print(dir(previous))
    for ag in previous.atom_groups(): # smarter?
      previous_c = ag.get_atom('C')
      previous_o = ag.get_atom('O')
    for ag in eta.atom_groups(): # needs to be conformers...
      atom_name = ' H  '
      if ag.get_atom(atom_name):
        assert 0
      else:
        for atom in ag.atoms(): print(atom.format_atom_record())
        rc = _add_hydrogens_to_atom_group_using_bad(
          ag,
          atom_name,
          proton_element,
          'N',
          previous_c, #'CA',
          previous_o, #'CB',
          1.,
          120.,
          180.,
          #append_to_end_of_model=append_to_end_of_model,
        )
        assert rc is not None
        print('-'*80)
        for atom in ag.atoms(): print(atom.format_atom_record())
  #      hierarchy.show()
  #assert 0

def generate_atom_group_atom_names(rg, names):
  '''
  Generate all alt. loc. groups of names
  '''
  atom_groups = rg.atom_groups()
  atom_altlocs = {}
  for ag in atom_groups:
    for atom in ag.atoms():
      atom_altlocs.setdefault(atom.parent().altloc, [])
      atom_altlocs[atom.parent().altloc].append(atom)
  keys = atom_altlocs.keys()
  if len(keys)>1 and '' in keys:
    for key in keys:
      if key=='': continue
      for atom in atom_altlocs['']:
        atom_altlocs[key].append(atom)
    del atom_altlocs['']
  for key, item in atom_altlocs.items():
    atoms=[]
    for name in names:
      for atom in item:
        if atom.name.strip()==name.strip():
          atoms.append(atom)
          break
      else:
        assert 0, 'atoms not found %s' % names
    yield atoms[0].parent(), atoms

def _h_h2_on_N(hierarchy,
               geometry_restraints_manager,
               verbose=False,
               ):
  from mmtbx.ligands.ready_set_utils import is_perdeuterated
  atoms = hierarchy.atoms()
  ###
  def get_residue_group(residue):
    for atom in residue.atoms():
      atom = atoms[atom.i_seq]
      break
    return atom.parent().parent()
  ###
  def get_atom_from_residue_group(residue, label):
    h = None
    for ag in residue.atom_groups():
      h = ag.get_atom(label)
      if h: break
    return h
  ###
  n_done = []
  for three in generate_protein_fragments(
    hierarchy,
    geometry_restraints_manager,
    backbone_only=False,
    #use_capping_hydrogens=use_capping_hydrogens,
    ):
    if len(three)==1: continue
    for i, residue in enumerate(three):
      if not i: continue
      residue = get_residue_group(residue)
      proton_name=proton_element='H'
      if is_perdeuterated(residue):
        proton_name=proton_element='D'
      h = get_atom_from_residue_group(residue, proton_name)
      if h is None:
        for ag, (n, ca, c) in generate_atom_group_atom_names(residue,
                                                             ['N', 'CA', 'C'],
                                                            ):
          if ag.resname in ['PRO']: continue
          if n in n_done: continue
          n_done.append(n)
          dihedral = 0
          rh3 = construct_xyz(n, 1.0,
                              ca, 109.5,
                              c, dihedral,
                            )
          atom = iotbx.pdb.hierarchy.atom()
          atom.name = ' %s  ' % proton_name
          atom.element = proton_element
          atom.xyz = rh3[0]
          atom.occ = n.occ
          atom.b = n.b
          atom.segid = ' '*4
          ag.append_atom(atom)
          assert ag.resname!='PRO'

def special_case_hydrogens(hierarchy,
                           geometry_restraints_manager,
                           verbose=False,
                          ):
  for special_case in [
      #_eta_peptide_h,
      _h_h2_on_N,
                       ]:
    rc = special_case(hierarchy,
                      geometry_restraints_manager,
                      verbose=verbose,
                      )
  hierarchy.sort_atoms_in_place()

def complete_pdb_hierarchy(hierarchy,
                           geometry_restraints_manager,
                           use_capping_hydrogens=False,
                           append_to_end_of_model=False,
                           pdb_filename=None,
                           pdb_inp=None,
                           original_pdb_filename=None,
                           verbose=False,
                           debug=False,
                          ):
  """Complete PDB hierarchy with hydrogen atoms as needed

  Args:
      hierarchy (hierarchy): Starting model
      geometry_restraints_manager (GRM): Starting restraints
      use_capping_hydrogens (bool, optional): Capping or not
      append_to_end_of_model (bool, optional): Added atoms go to end of atom list
      pdb_filename (None, optional): Description
      pdb_inp (None, optional): Description
      original_pdb_filename (None, optional): Description
      verbose (bool, optional): Description
      debug (bool, optional): Description

  Returns:
      TYPE: Description

  Raises:
      Sorry: Description
  """
  #
  # some validations
  #
  for ag in hierarchy.atom_groups():
    if get_class(ag.resname) in ['common_rna_dna']:
      raise Sorry('Nucleotides are not currently supported. e.g. %s' % ag.resname)
  if not is_hierarchy_altloc_consistent(hierarchy):
    is_hierarchy_altloc_consistent(hierarchy, verbose=True)
    raise Sorry('Altloc structure of model not consistent. Make each altloc the same depth or remove completely.')
  from mmtbx.building import extend_sidechains
  original_hierarchy = None
  params = hierarchy_utils.get_pdb_interpretation_params()
  params.restraints_library.cdl=False
  if use_capping_hydrogens:
    params.link_distance_cutoff=1.8 # avoid linking across a single missing AA
    if original_pdb_filename:
      original_pdb_inp = iotbx.pdb.input(original_pdb_filename)
      original_hierarchy = original_pdb_inp.construct_hierarchy()
  if debug:
    output = hierarchy_utils.write_hierarchy(pdb_filename,
                                             pdb_inp,
                                             hierarchy,
                                             'temp1',
                                           )
  #
  # assume model is heavy-atom complete
  #
  if not use_capping_hydrogens:
    if debug:
      ppf = hierarchy_utils.get_processed_pdb(pdb_filename=output)
    else:
      raw_records = hierarchy_utils.get_raw_records(pdb_inp, hierarchy)
      ppf = hierarchy_utils.get_processed_pdb(raw_records=raw_records,
                                              params=params,
                                            )
      sites_cart = hierarchy.atoms().extract_xyz()
      ppf.all_chain_proxies.pdb_hierarchy.atoms().set_xyz(sites_cart)
    n_changed = extend_sidechains.extend_protein_model(
      ppf.all_chain_proxies.pdb_hierarchy,
      mon_lib_server,
      add_hydrogens=False,
    )
    if debug:
      print('number of side chains changed',n_changed)
      output = hierarchy_utils.write_hierarchy(pdb_filename,
                                               pdb_inp,
                                               ppf.all_chain_proxies.pdb_hierarchy,
                                               'temp2',
                                             )
  #
  # need to use Reduce/ReadySet! to add hydrogens
  #
  if not use_capping_hydrogens:
    output = hierarchy_utils.write_hierarchy(
      pdb_filename,
      pdb_inp,
      ppf.all_chain_proxies.pdb_hierarchy,
      'readyset_input',
    )
    hierarchy = hierarchy_utils.add_hydrogens_using_ReadySet(output)
  #
  # remove side chain acid hydrogens - maybe not required since recent changes
  #
  if debug:
    ppf = hierarchy_utils.get_processed_pdb(pdb_filename=output,
                                            params=params,
                                          )
  else:
    raw_records = hierarchy_utils.get_raw_records(pdb_inp, hierarchy)
    ppf = hierarchy_utils.get_processed_pdb(raw_records=raw_records,
                                            params=params,
                                          )
    sites_cart = hierarchy.atoms().extract_xyz()
    ppf.all_chain_proxies.pdb_hierarchy.atoms().set_xyz(sites_cart)
  remove_acid_side_chain_hydrogens(ppf.all_chain_proxies.pdb_hierarchy)
  #
  # add hydrogens in special cases
  #  eg ETA
  #  eg N - H, H2
  #
  if debug:
    ppf = hierarchy_utils.get_processed_pdb(pdb_filename=output,
                                            params=params,
                                          )
  else:
    hierarchy = ppf.all_chain_proxies.pdb_hierarchy
    raw_records = hierarchy_utils.get_raw_records(pdb_inp, hierarchy)
    ppf = hierarchy_utils.get_processed_pdb(raw_records=raw_records,
                                            params=params,
                                          )
    sites_cart = hierarchy.atoms().extract_xyz()
    ppf.all_chain_proxies.pdb_hierarchy.atoms().set_xyz(sites_cart)
  special_case_hydrogens(ppf.all_chain_proxies.pdb_hierarchy,
                         ppf.geometry_restraints_manager(),
                         #use_capping_hydrogens=use_capping_hydrogens,
                         #append_to_end_of_model=append_to_end_of_model,
                         #original_hierarchy=original_hierarchy,
                         verbose=verbose,
                       )
  #
  # add terminals atoms including hydrogens and OXT - more docs here...
  #
  if debug:
    output = hierarchy_utils.write_hierarchy(
      pdb_filename,
      pdb_inp,
      ppf.all_chain_proxies.pdb_hierarchy,
      'temp3',
    )
    ppf = hierarchy_utils.get_processed_pdb(pdb_filename=output,
                                            params=params,
                                           )
  else:
    hierarchy = ppf.all_chain_proxies.pdb_hierarchy
    raw_records = hierarchy_utils.get_raw_records(pdb_inp, hierarchy)
    ppf = hierarchy_utils.get_processed_pdb(raw_records=raw_records,
                                            params=params,
                                           )
    sites_cart = hierarchy.atoms().extract_xyz()
    ppf.all_chain_proxies.pdb_hierarchy.atoms().set_xyz(sites_cart)
  #
  # moved to mmtbx.ligands
  #
  add_terminal_hydrogens(ppf.all_chain_proxies.pdb_hierarchy,
                         ppf.geometry_restraints_manager(),
                         use_capping_hydrogens=use_capping_hydrogens,
                         append_to_end_of_model=append_to_end_of_model,
                         original_hierarchy=original_hierarchy,
                         verbose=verbose,
                        ) # in place
  if debug:
    output = hierarchy_utils.write_hierarchy(
      pdb_filename,
      pdb_inp,
      ppf.all_chain_proxies.pdb_hierarchy,
      'temp8',
    )
  ppf.all_chain_proxies.pdb_hierarchy.atoms().set_chemical_element_simple_if_necessary()
  ppf.all_chain_proxies.pdb_hierarchy.sort_atoms_in_place()
  if debug:
    output = hierarchy_utils.write_hierarchy(
      pdb_filename,
      pdb_inp,
      ppf.all_chain_proxies.pdb_hierarchy,
      'temp9',
    )
  #display_hierarchy_atoms(ppf.all_chain_proxies.pdb_hierarchy)
  #ppf.all_chain_proxies.pdb_hierarchy.atoms_reset_serial()
  #ppf.all_chain_proxies.pdb_hierarchy.atoms().reset_i_seq()
  return ppf

def run(pdb_filename=None,
        pdb_hierarchy=None,
        crystal_symmetry=None,
        model_completion=True,
        original_pdb_filename=None,
        append_to_end_of_model=True,
        ):
  #
  # function as be used in two main modes
  #   1. completing a model with hydrogens in a protein-like manner
  #   2. completing a cluster with hydrogens in a QM-sensible manner
  #
  # Validation
  #
  if pdb_hierarchy:
    assert crystal_symmetry
    assert pdb_filename is None
  #
  # output
  #
  if model_completion:
    use_capping_hydrogens=False
    fname = 'complete'
  else:
    use_capping_hydrogens=True
    fname = 'capping'
  #
  # adjust parameters
  #
  params=None
  if use_capping_hydrogens:
    params = hierarchy_utils.get_pdb_interpretation_params()
    params.link_distance_cutoff=1.8
  if pdb_hierarchy:
    raw_records = hierarchy_utils.get_raw_records(
      pdb_inp=None,
      pdb_hierarchy=pdb_hierarchy,
      crystal_symmetry=crystal_symmetry,
    )
    ppf = hierarchy_utils.get_processed_pdb(raw_records=raw_records)
    sites_cart = pdb_hierarchy.atoms().extract_xyz()
    ppf.all_chain_proxies.pdb_hierarchy.atoms().set_xyz(sites_cart)
  else:
    ppf = hierarchy_utils.get_processed_pdb(pdb_filename=pdb_filename,
                                            params=params,
                                          )
  #
  # guts
  #
  ppf = complete_pdb_hierarchy(
    ppf.all_chain_proxies.pdb_hierarchy,
    ppf.geometry_restraints_manager(),
    use_capping_hydrogens=use_capping_hydrogens,
    append_to_end_of_model=append_to_end_of_model, # needed for clustering
                                                   # code and Molprobity
    pdb_filename=pdb_filename,   # used just for naming of debug output
    pdb_inp=ppf.all_chain_proxies.pdb_inp, # used in get_raw_records. why
    verbose=False,
  )
  if pdb_filename:
    output = hierarchy_utils.write_hierarchy(
      pdb_filename,
      ppf.all_chain_proxies.pdb_inp,
      ppf.all_chain_proxies.pdb_hierarchy,
      fname,
    )
  return ppf.all_chain_proxies.pdb_hierarchy

def display_hierarchy_atoms(hierarchy, n=5):
  print('-'*80)
  for i, atom in enumerate(hierarchy.atoms()):
    print(atom.quote())
    if i>n: break

if __name__=="__main__":
  def _fake_phil_parse(arg):
    def _boolean(s):
      if s.lower() in ['1', 'true']: return True
      elif s.lower() in ['0', 'false']: return False
      else: return s
    rc = {arg.split('=')[0] : _boolean(arg.split('=')[1])}
    return rc
  args = sys.argv[1:]
  del sys.argv[1:]
  kwds={}
  remove=[]
  for i, arg in enumerate(args):
    if arg.find('=')>-1:
      kwds.update(_fake_phil_parse(arg))
      remove.append(i)
  remove.reverse()
  for r in remove: del args[r]
  if 'test_from_clustering' in args:
    args.remove('test_from_clustering')
    ppf = hierarchy_utils.get_processed_pdb(args[0])
    sites_cart = ppf.all_chain_proxies.pdb_hierarchy.atoms().extract_xyz()
    sites_cart[0]=(4.123456789, 7.7, 1.5)
    ppf.all_chain_proxies.pdb_hierarchy.atoms().set_xyz(sites_cart)
    kwds['pdb_hierarchy'] = ppf.all_chain_proxies.pdb_hierarchy
    kwds['crystal_symmetry'] = ppf.all_chain_proxies.pdb_inp.crystal_symmetry()
    display_hierarchy_atoms(kwds['pdb_hierarchy'])
    rc = run(None, **kwds)
    #print '='*80
    display_hierarchy_atoms(rc)
    assert 0, 'FINISHED TESTING'
  #print 'run',args,kwds
  run(*tuple(args), **kwds)
