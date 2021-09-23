# coding: utf-8
import logging
import sys
import time

import pytest

import ray.cluster_utils
import ray._private.test_utils

import ray

import pandas as pd

logger = logging.getLogger(__name__)

# This test compares the scheduling latency of Raylet-based scheduler and
# GCS-based scheduler.
n = 64
num_upper = 4


@pytest.mark.parametrize("args", [
    [n, n, num_upper, False, False],
    [n, n, num_upper, False, True],
])
#[[n, n, num_upper, False, True],])
#[n, n, num_upper, True, False]])
def test_actor_scheduling_latency(ray_start_cluster, args):
    cluster = ray_start_cluster

    # The total count of nodes.
    node_count = args[0]
    # The total count of actors.
    actor_count = args[1]
    # The count of upper actors.
    upper_count = args[2]
    # Whether to enable gcs-based scheduler.
    gcs_sched = args[3]

    scheduler_new = args[4]

    print(["raylet", "gcs"][gcs_sched], ["old", "new"][scheduler_new])
    for i in range(node_count):
        cluster.add_node(
            memory=4 * 1024**2,
            num_cpus=4,
            _system_config={
                "gcs_actor_scheduling_enabled": gcs_sched,
                "scheduler_old": not scheduler_new
            }
            #_system_config={"gcs_actor_scheduling_enabled": gcs_sched}
            if i == 0 else {})
    ray.init(address=cluster.address)
    cluster.wait_for_nodes()

    # Driver will create all UpperActors, and then each UpperActor will
    # create BottomActors independently.
    @ray.remote(memory=1024**2, num_cpus=1)
    class UpperActor:
        def __init__(self):
            self.start = time.time()

        def info(self):
            return [ray.worker.global_worker.node.unique_id, self.start]

        def create(self, num):
            ret_list = []
            for _ in range(num):
                start_time = time.time()
                ret_list.append([start_time, BottomActor.remote()])
            return ret_list

    @ray.remote(memory=1024**2, num_cpus=1)
    class BottomActor:
        def __init__(self):
            self.start = time.time()

        def info(self):
            return [ray.worker.global_worker.node.unique_id, self.start]

    actor_distribution = {}
    actor_list = []
    start_list = []
    end_list = []
    ref_list = []

    # Create UpperActors.
    for _ in range(upper_count):
        start_list.append(time.time())
        actor_list.append(UpperActor.remote())

    # UpperActors create BottomActors.
    for actor in actor_list:
        ref_list.append(
            actor.create.remote(
                int((actor_count - upper_count) / upper_count)))
    for ref in ref_list:
        ret_list = ray.get(ref)
        for ret in ret_list:
            start_list.append(ret[0])
            actor_list.append(ret[1])

    for actor in actor_list:
        ret_list = ray.get(actor.info.remote())
        if ret_list[0] not in actor_distribution.keys():
            actor_distribution[ret_list[0]] = []
        actor_distribution[ret_list[0]].append(actor)
        end_list.append(ret_list[1])

    # assert len(actor_distribution) == node_count
    # for node_id, actors in actor_distribution.items():
    #     assert len(actors) <= int(actor_count / node_count)

    latency_list = []
    for i in range(actor_count):
        latency_list.append(end_list[i] - start_list[i])
        ##print(latency_list[i])
    print(
        pd.Series(latency_list).describe(
            percentiles=[0.25, 0.5, 0.75, 0.9, 0.99]))


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main(["-v", __file__]))
