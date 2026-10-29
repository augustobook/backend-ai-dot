"""PyTorch runtime helpers shared by the embedding model and the cross-encoder."""

import logging
from typing import Literal

import torch

logger = logging.getLogger(__name__)


def resolve_device(preference: Literal["auto", "cpu", "cuda"]) -> torch.device:
    """Pick the device where the models run.

    Args:
        preference: "auto" uses the GPU when one is available, otherwise the CPU.

    Returns:
        The selected torch device.

    Raises:
        ValueError: If "cuda" is requested but no GPU is available.
    """
    if preference == "cuda" and not torch.cuda.is_available():
        raise ValueError("DEVICE=cuda was requested, but no CUDA GPU is available.")
    if preference == "auto":
        preference = "cuda" if torch.cuda.is_available() else "cpu"
    return torch.device(preference)


def configure_torch_threads(num_threads: int | None) -> None:
    """Limit the CPU threads used by PyTorch.

    Useful in containers, where PyTorch may see every host core and oversubscribe
    the CPU quota given to the container.

    Args:
        num_threads: Number of threads, or None to keep the library default.
    """
    if num_threads is not None:
        torch.set_num_threads(num_threads)
        logger.info("PyTorch limited to %d CPU threads", num_threads)
