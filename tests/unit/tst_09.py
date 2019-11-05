from __future__ import division

import time
import os
import os.path
import libtbx.load_env
from libtbx.test_utils import approx_equal
import iotbx.pdb
from mmtbx.pair_interaction import pair_interaction
import run_tests

qrefine = libtbx.env.find_in_repositories("qrefine")
qr_unit_tests = os.path.join(qrefine, "tests","unit")


def run(prefix):
  """
  Exercise buffer region of cluster.
  """
  # XXX Remove once move to C++ version
  from qrefine import qr
  p = qr.get_master_phil().extract()
  fast_interaction = p.cluster.fast_interaction
  #

  pdb_inp = iotbx.pdb.input(file_name= os.path.join(qr_unit_tests,"data_files","2lvr.pdb"))
  ph = pdb_inp.construct_hierarchy()

  # To be deprecated
  pyoink = None
  if(not fast_interaction):
    from qrefine.utils import yoink_utils
    from qrefine.plugin.yoink.pyoink import PYoink
    yoink_utils.write_yoink_infiles("cluster.xml",
                                  "qmmm.xml",
                                  ph,
                                  os.path.join(qrefine,"plugin","yoink","dat"))
    pyoink = PYoink(os.path.join(qrefine,"plugin","yoink","Yoink-0.0.1.jar"),
                               os.path.join(qrefine,"plugin","yoink","dat"),
                               "qmmm.xml")

  # Clusters
  bc_clusters = [[1, 2],
                  [3, 4, 5, 13, 14, 15, 16, 17, 18, 19, 20, 21],
                  [6, 7, 8, 9, 10, 11, 12, 22, 23, 26, 31],
                  [24, 25, 27, 28, 29, 30]]

  # Framgents = cluster + buffer
  bc_qms = [[1, 2, 3, 4], [1, 2, 3, 4, 5, 6, 7, 10, 11, 12, 13, 14, 15, 16, 17,
                           18, 19, 20, 21, 22, 23, 24, 25],
            [3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 31],
            [20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30]]

  gn_clusters = [[1, 2],
                  [3, 4, 5, 14, 13],
                  [6, 7, 8, 9, 22, 23, 26, 31],
                  [10, 11, 12],
                  [15, 16, 17, 18, 19, 20, 21],
                  [24, 25, 27, 28, 29, 30]]

  gn_qms = [[1, 2, 3, 4], [1, 2, 3, 4, 5, 6, 7, 10, 11, 12, 13, 14, 15, 16, 18, 19, 22],
         [5, 6, 7, 8, 9, 10, 11, 13, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 31],
         [3, 5, 6, 9, 10, 11, 12, 13, 22],
         [4, 5, 6, 7, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25],
         [20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30]]

  check_buffer(ph, bc_clusters, bc_qms, pyoink=pyoink)

def check_buffer(ph, clusters, qms, pyoink):
  # XXX Remove once move to C++ version
  from qrefine import qr
  p = qr.get_master_phil().extract()
  fast_interaction = p.cluster.fast_interaction
  #
  qms_calculated = []
  for i in range(len(clusters)):
    if(fast_interaction):
      fragment = pair_interaction.run(ph, core=clusters[i])[2]
      qms_calculated.append(fragment)
    else:
      assert pyoink is not None
      pyoink.update(clusters[i])
      qm_atoms, qm_molecules = pyoink.get_qm_indices()
      qms_calculated.append(list(qm_molecules))
  print "qms calc: ",qms_calculated
  assert approx_equal(qms, qms_calculated)

if(__name__ == "__main__"):
  prefix = os.path.basename(__file__).replace(".py","")
  run_tests.runner(function=run, prefix=prefix, disable=False)
