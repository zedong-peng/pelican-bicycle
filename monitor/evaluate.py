"""Run one upstream candy sample unchanged; supervisor enforces timeout."""
import importlib.util
import json
import os

spec = importlib.util.spec_from_file_location('candy', os.environ['CANDY_SCRIPT'])
candy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(candy)
answer, input_tokens, output_tokens, reasoning_tokens = candy.run_codex('gpt-6-astra', 'low')
print(json.dumps({'ok': bool(candy.ANSWER_PATTERN.search(answer)), 'answer': answer,
                  'input_tokens': input_tokens, 'output_tokens': output_tokens,
                  'reasoning_tokens': reasoning_tokens}, ensure_ascii=False))
