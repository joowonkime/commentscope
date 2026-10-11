"""Pinned, offline English NLI comparator. Not a calibrated approval gate."""
import math
import time

MODEL = 'MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli'
REVISION = '6f5cf0a2b59cabb106aca4c287eed12e357e90eb'
THRESHOLD = 0.8  # Fixed before development run; softmax is not calibrated confidence.
LABELS = {'entailment': 'supports', 'neutral': 'not_established', 'contradiction': 'contradicts'}


def decide(scores, threshold=THRESHOLD):
    if set(scores) != set(LABELS):
        raise ValueError('Unexpected NLI label mapping')
    if not 0.5 < threshold <= 1:
        raise ValueError('Invalid threshold')
    if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in scores.values()):
        raise ValueError('Invalid probabilities')
    if abs(sum(scores.values()) - 1) > 1e-5:
        raise ValueError('Probabilities must sum to one')
    winner = max(scores, key=scores.get)
    return LABELS[winner] if scores[winner] >= threshold else 'unclear'


class LocalNLI:
    def __init__(self):
        import torch
        import transformers
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        started = time.perf_counter()
        self.torch = torch
        torch.set_num_threads(6)
        torch.manual_seed(407)
        self.tokenizer = AutoTokenizer.from_pretrained(
            MODEL, revision=REVISION, local_files_only=True, trust_remote_code=False)
        self.model = AutoModelForSequenceClassification.from_pretrained(
            MODEL, revision=REVISION, local_files_only=True, trust_remote_code=False,
            use_safetensors=True).to('cpu').eval()
        self.labels = {int(k): v.lower() for k, v in self.model.config.id2label.items()}
        if set(self.labels) != {0, 1, 2} or set(self.labels.values()) != set(LABELS):
            raise ValueError('Unexpected model label mapping')
        self.metadata = {'model': MODEL, 'revision': REVISION, 'device': 'cpu', 'dtype': 'float32',
            'torch': torch.__version__, 'transformers': transformers.__version__, 'threads': 6,
            'threshold': THRESHOLD, 'calibrated': False, 'id2label': self.labels,
            'local_files_only': True, 'trust_remote_code': False, 'use_safetensors': True,
            'load_seconds': time.perf_counter() - started, 'language_scope': 'English only'}

    def score(self, source, representative):
        started = time.perf_counter()
        record = {'origin': 'local_nli', 'relation': None, 'errors': [], 'human_approved': False,
                  'raw': None, 'output': None, 'scores': None}
        try:
            if not all(isinstance(t, str) and t.strip() and len(t) <= 500 for t in (source, representative)):
                raise ValueError('invalid_text')
            # Premise first, hypothesis second. Never silently truncate qualifications.
            inputs = self.tokenizer(source, representative, return_tensors='pt', truncation=False)
            record['input_tokens'] = inputs['input_ids'].shape[1]
            if record['input_tokens'] > min(512, self.model.config.max_position_embeddings):
                raise ValueError('input_too_long')
            with self.torch.inference_mode():
                logits = self.model(**inputs).logits[0]
                values = logits.softmax(dim=-1).tolist()
            record['raw'] = logits.tolist()
            record['scores'] = {self.labels[i]: value for i, value in enumerate(values)}
            record['argmax_relation'] = LABELS[max(record['scores'], key=record['scores'].get)]
            record['relation'] = decide(record['scores'])
            record['output'] = {'relation': record['relation']}
        except (ValueError, RuntimeError, OSError) as exc:
            record['errors'] = [type(exc).__name__]
            record['relation'] = None
        record['seconds'] = time.perf_counter() - started
        return record
