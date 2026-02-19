"""
SWE-bench benchmark configuration.

Default values aligned with evaluation repository (OpenHands/evaluation).
"""

# Inference defaults (used by run_infer.py)
INFER_DEFAULTS = {
    "dataset": "princeton-nlp/SWE-bench_Verified",
    "split": "test",
    "num_workers": 30,
}

# Modal sandbox inference defaults (used by run_infer_modal.py)
INFER_MODAL_DEFAULTS = {
    "sandbox_timeout": 3600,
    "sandbox_idle_timeout": 900,
    "sandbox_cpu": 4.0,
    "sandbox_memory_mib": 8192,
    "modal_concurrency": 8,
}

# Evaluation defaults (used by eval_infer.py)
EVAL_DEFAULTS = {
    "dataset": "princeton-nlp/SWE-bench_Verified",
    "split": "test",
    "workers": 12,
    "modal": True,
    "timeout": 3600,
}

# Build defaults (used by build_images.py)
BUILD_DEFAULTS = {
    "max_workers": 32,
}
