"""Same pinned NLI weights, full source token budget instead of a 500-char veto."""
import time

from commentscope.providers.local_nli import LABELS, decide


def score_full(model, source, target):
    started = time.perf_counter()
    result = {'origin': 'local_nli_full_source', 'relation': None, 'errors': [],
              'human_approved': False, 'raw': None, 'output': None, 'scores': None,
              'deferred_reason': None}
    try:
        if not all(isinstance(x, str) and x.strip() for x in (source, target)):
            raise ValueError('Empty input')
        if len(source) > 4000 or len(target) >= 250:
            result['errors'] = ['input_budget']; result['deferred_reason'] = 'character_budget'
        else:
            inputs = model.tokenizer(source, target, return_tensors='pt', truncation=False)
            result['input_tokens'] = inputs['input_ids'].shape[1]
            if result['input_tokens'] > min(512, model.model.config.max_position_embeddings):
                result['errors'] = ['input_budget']; result['deferred_reason'] = 'token_budget'
            else:
                with model.torch.inference_mode():
                    logits = model.model(**inputs).logits[0]
                    values = logits.softmax(dim=-1).tolist()
                result['raw'] = logits.tolist()
                result['scores'] = {model.labels[i]: v for i, v in enumerate(values)}
                result['argmax_relation'] = LABELS[max(result['scores'], key=result['scores'].get)]
                result['relation'] = decide(result['scores'])
                result['output'] = {'relation': result['relation']}
    except (ValueError, RuntimeError, OSError) as exc:
        result['errors'] = [type(exc).__name__]
    result['seconds'] = time.perf_counter() - started
    return result
