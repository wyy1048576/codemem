"""codemem embedder plugin for Intel Arc: `vectors.<type>.embedder = "arc_embedder:ArcEmbedder"`.

On this Arc GPU, PyTorch XPU returned wrong vectors for batches with fewer than about 1,024 token
slots (batch size x padded length), with no error. So:
- documents run on Arc in float16, as on the Mac run, and each batch is padded to at least
  MIN_SLOTS token slots. The attention mask hides the padding from the model and the pooling;
- queries run one at a time on the CPU in true float32. There are few of them.
"""
from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
import torch
from codemem.embedder import Embedder, SentenceTransformerEmbedder

MIN_SLOTS = 1024
BATCH_SIZE = 32


class ArcEmbedder(Embedder):
    def __init__(self, model_name: str, config):
        self.model_name = model_name
        length = config.max_seq_length
        self.doc = SentenceTransformerEmbedder(model_name, device="xpu", batch_size=BATCH_SIZE, max_seq_length=length, dtype="float16")
        self.query = SentenceTransformerEmbedder(model_name, device="cpu", batch_size=1, max_seq_length=length, dtype="float32")
        self._doc_ready = False
        self._query_ready = False

    @property
    def ready(self) -> bool:
        return self._doc_ready

    @property
    def dim(self) -> int:
        self._prepare_doc()
        return self.doc.dim

    def _prepare_doc(self) -> None:
        if self._doc_ready:
            return
        if self.doc.device != "xpu":
            raise RuntimeError("ArcEmbedder needs PyTorch XPU; refusing to embed on another device")
        model = self.doc.model
        transformer = model[0]
        if model.tokenizer.padding_side != "right":
            raise RuntimeError("ArcEmbedder expects right padding")
        pad_id = model.tokenizer.pad_token_id
        inner = transformer.forward

        def forward(features, **kwargs):
            ids = features["input_ids"]
            rows, length = ids.shape
            wanted = math.ceil(MIN_SLOTS / rows)
            if length < wanted:
                for name in ("input_ids", "attention_mask", "token_type_ids"):
                    if name in features:
                        value = pad_id if name == "input_ids" else 0
                        extra = torch.full((rows, wanted - length), value, dtype=features[name].dtype, device=features[name].device)
                        features[name] = torch.cat([features[name], extra], dim=1)
            return inner(features, **kwargs)

        transformer.forward = forward
        self._doc_ready = True

    def _prepare_query(self) -> None:
        if not self._query_ready:
            self.query.model.to(torch.float32)  # the checkpoint loads as bfloat16 unless converted
            self._query_ready = True

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        self._prepare_doc()
        return self.doc.embed_documents(texts)

    def embed_queries(self, texts: Sequence[str]) -> np.ndarray:
        self._prepare_query()
        return self.query.embed_queries(texts)
