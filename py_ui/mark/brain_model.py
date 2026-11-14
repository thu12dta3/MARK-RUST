
from __future__ import annotations
import urllib.request
from dataclasses import asdict
from .cognition.telemetry import record_metrics
from .cognition.providers import ModelRequest, get_provider
from .core.context import current_context
from .core.events import CoreEvent, events

class EngineerModelError(RuntimeError):
    pass

def _ollama(prompt: str, cfg: dict, system=None, image=None, num_predict=None,
            output_format=None, images: list[str] | None = None, history=None) -> str:
    context = current_context()
    request = ModelRequest(prompt, system, image, tuple(images or ()), num_predict, output_format,
                           history=tuple(history or ()), context=context)
    provider = get_provider(cfg)
    provider_name = str(cfg.get('cognition', {}).get('model_provider', 'ollama'))[:64]
    profile = cfg.get('interaction_mode', 'chat')
    model = str((cfg.get('models') or {}).get(profile) or cfg.get('ollama', {}).get('model', 'unknown'))[:256]
    if not images and not image and any(k in model.lower() for k in ("markvl", "mark-vl")):
        import copy
        fallback = cfg.get('models', {}).get('chat') or 'haervwe/qwen3-vl-4b-heretic:latest'
        if any(k in fallback.lower() for k in ("markvl", "mark-vl")):
            fallback = 'haervwe/qwen3-vl-4b-heretic:latest'
        cfg = copy.deepcopy(cfg)
        cfg.setdefault('models', {})[profile] = fallback
        cfg.setdefault('ollama', {})['model'] = fallback
        model = fallback
        provider = get_provider(cfg)
    events.publish(CoreEvent('mark.model.request.started', context,
                             metadata={'provider': provider_name, 'model': model}))
    try:
        response = provider.generate(request)
    except Exception as exc:
        events.publish(CoreEvent('mark.model.request.failed', context,
                                 metadata={'provider': provider_name, 'model': model,
                                           'status': 'failed', 'error_type': type(exc).__name__}))
        if cfg.get('interaction_mode') == 'engineer':
            raise EngineerModelError('O modelo especializado do Engineer falhou.') from exc
        raise
    else:
        metrics = response.metrics
        events.publish(CoreEvent('mark.model.request.completed', context,
                                 metadata={'provider': provider_name, 'model': model,
                                           'status': 'completed', 'latency_ms': metrics.latency_ms,
                                           'prompt_tokens': metrics.prompt_tokens,
                                           'output_tokens': metrics.output_tokens}))
        return response.text
    finally:
        if getattr(provider, 'last_metrics', None):
            try: record_metrics(asdict(provider.last_metrics), cfg)
            except (OSError, ValueError): pass
