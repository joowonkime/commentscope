"""Pinned local-only OpenJev comparator, NOT TypeSafe's commercial Jev.

Optional isolated torch/transformers environment. No generation, remote model
code, truncation, production default changes, or calibrated-confidence claim.
"""
import time

from commentscope.providers.local_nli import decide, LABELS, THRESHOLD

MODEL = 'AlexWortega/openjev'
REVISION = 'a20448012c213128955ca0c693e7c943865cab77'
SUBFOLDER = 'qwen3.5-2b-nli-v5'
TEMPLATE = 'Premise: {premise}\nHypothesis: {hypothesis}'
LABEL_MAP = {0: 'contradiction', 1: 'entailment', 2: 'neutral'}


def format_pair(source, target):
    if not all(isinstance(s, str) and s.strip() and len(s) <= 500 for s in (source, target)):
        raise ValueError('invalid_text')
    return TEMPLATE.format(premise=source, hypothesis=target)


class LocalOpenJev:
    def __init__(self, device='cuda'):
        if device not in ('cpu', 'cuda'): raise ValueError('Invalid device')
        import torch
        import transformers
        from transformers import AutoConfig, AutoModelForSequenceClassification, AutoTokenizer
        started = time.perf_counter()
        self.torch, self.device = torch, device
        torch.set_num_threads(6)
        torch.manual_seed(407)
        if device == 'cuda' and not torch.cuda.is_available():
            raise RuntimeError('CUDA unavailable; no silent device fallback')
        kw = dict(revision=REVISION, subfolder=SUBFOLDER, local_files_only=True, trust_remote_code=False)
        config = AutoConfig.from_pretrained(MODEL, **kw)
        if (config.architectures != ['Qwen3_5ForSequenceClassification'] or
                config.nli_template != TEMPLATE or
                {int(k): v for k, v in config.id2label.items()} != LABEL_MAP):
            raise ValueError('Unexpected OpenJev checkpoint contract')
        self.tokenizer = AutoTokenizer.from_pretrained(MODEL, **kw)
        self.tokenizer.padding_side = 'right'
        if self.tokenizer.pad_token_id is None: raise ValueError('Missing pad token')
        dtype = torch.bfloat16 if device == 'cuda' else torch.float32
        self.model = AutoModelForSequenceClassification.from_pretrained(
            MODEL, **kw, dtype=dtype, use_safetensors=True).to(device).eval()
        if self.model.config.get_text_config().pad_token_id != self.tokenizer.pad_token_id:
            raise ValueError('Pooling pad token mismatch')
        self.sync()
        self.metadata = {'model': MODEL, 'revision': REVISION, 'subfolder': SUBFOLDER,
                         'device': device, 'dtype': str(dtype), 'threads': 6,
                         'torch': torch.__version__, 'transformers': transformers.__version__,
                         'id2label': LABEL_MAP, 'template': TEMPLATE, 'threshold': THRESHOLD,
                         'calibrated': False, 'max_input_tokens': 512, 'max_chars_per_text': 500,
                         'local_files_only': True, 'trust_remote_code': False,
                         'use_safetensors': True, 'batch_size': 1,
                         'load_seconds': time.perf_counter()-started,
                         'language_scope': 'English diagnostic only; not a multilingual quality claim',
                         'hardware': torch.cuda.get_device_name() if device == 'cuda' else 'cpu'}

    def sync(self):
        if self.device == 'cuda': self.torch.cuda.synchronize()

    def score(self, source, target):
        self.sync()
        started = time.perf_counter()
        result = {'origin': 'local_openjev', 'relation': None, 'errors': [], 'human_approved': False,
                  'raw': None, 'output': None, 'scores': None}
        try:
            text = format_pair(source, target)
            inputs = self.tokenizer(text, return_tensors='pt', truncation=False)
            result['input_tokens'] = inputs['input_ids'].shape[1]
            if result['input_tokens'] > 512: raise ValueError('input_too_long')
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            if self.device == 'cuda': self.torch.cuda.reset_peak_memory_stats()
            with self.torch.inference_mode():
                logits = self.model(**inputs).logits[0].float()
                values = logits.softmax(dim=-1).tolist()
            result['raw'] = logits.tolist()
            result['scores'] = {LABEL_MAP[i]: v for i, v in enumerate(values)}
            result['relation'] = decide(result['scores'])
            result['argmax_relation'] = LABELS[max(result['scores'], key=result['scores'].get)]
            result['output'] = {'relation': result['relation']}
            if self.device == 'cuda':
                result['peak_allocated_bytes'] = self.torch.cuda.max_memory_allocated()
                result['peak_reserved_bytes'] = self.torch.cuda.max_memory_reserved()
        except (ValueError, RuntimeError, OSError) as exc:
            result['errors'] = [type(exc).__name__]
            result['relation'] = None
        self.sync()
        result['seconds'] = time.perf_counter()-started
        return result
