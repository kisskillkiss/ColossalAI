import torch
import colossalai
import pytest
import torch.multiprocessing as mp
from functools import partial
from colossalai.gemini.chunk import ChunkManager
from colossalai.testing import rerun_if_address_is_in_use, parameterize
from colossalai.utils import free_port
from colossalai.tensor import ProcessGroup, ColoTensor, ColoTensorSpec
from tests.test_tensor.common_utils import debug_print

CUDA_MEM_0 = {False: 512, True: 1024}
CUDA_MEM_1 = {False: 0, True: 1024}
CPU_MEM = {True: {True: 0, False: 0}, False: {True: 512, False: 0}}


@parameterize('keep_gathered', [True, False])
@parameterize('pin_memory', [True, False])
def exam_chunk_memory(keep_gathered, pin_memory):
    pg = ProcessGroup()

    debug_print([0], "keep_gathered: {}, pin_memory: {}".format(keep_gathered, pin_memory))

    params = [ColoTensor(torch.rand(8, 8), spec=ColoTensorSpec(pg)) for _ in range(3)]
    config = {2: dict(chunk_size=128, keep_gathered=keep_gathered)}

    chunk_manager = ChunkManager(config)
    assert chunk_manager.total_mem['cpu'] == 0
    assert chunk_manager.total_mem['cuda'] == 0

    for p in params:
        chunk_manager.append_tensor(p, 'param', 2, pin_memory=pin_memory)
    chunk_manager.close_all_groups()
    assert chunk_manager.total_mem['cpu'] == CPU_MEM[keep_gathered][pin_memory]
    assert chunk_manager.total_mem['cuda'] == CUDA_MEM_0[keep_gathered]

    chunks = chunk_manager.get_chunks(params)

    for chunk in chunks:
        chunk_manager.access_chunk(chunk)
    assert chunk_manager.total_mem['cpu'] == CPU_MEM[keep_gathered][pin_memory]
    assert chunk_manager.total_mem['cuda'] == CUDA_MEM_0[True]

    for chunk in chunks:
        chunk_manager.release_chunk(chunk)

    assert chunk_manager.total_mem['cpu'] == CPU_MEM[keep_gathered][pin_memory]
    assert chunk_manager.total_mem['cuda'] == CUDA_MEM_0[keep_gathered]

    for chunk in chunks:
        chunk_manager.move_chunk(chunk, torch.device('cpu'))
    assert chunk_manager.total_mem['cpu'] == CPU_MEM[keep_gathered][True]
    assert chunk_manager.total_mem['cuda'] == CUDA_MEM_1[keep_gathered]


def run_dist(rank, world_size, port):
    colossalai.launch(config={}, rank=rank, world_size=world_size, host='localhost', port=port, backend='nccl')
    exam_chunk_memory()


@pytest.mark.dist
@pytest.mark.parametrize('world_size', [2])
@rerun_if_address_is_in_use()
def test_chunk_manager(world_size):
    run_func = partial(run_dist, world_size=world_size, port=free_port())
    mp.spawn(run_func, nprocs=world_size)


if __name__ == '__main__':
    test_chunk_manager(2)
