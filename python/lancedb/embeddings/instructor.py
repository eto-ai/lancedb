from functools import lru_cache
from typing import List

import numpy as np

from .base import TextEmbeddingFunction
from .registry import register
from .utils import TEXT, weak_lru


@register("instructor")
class InstuctorEmbeddingFunction(TextEmbeddingFunction):
    """
    An embedding function that uses the InstructorEmbedding library. Instructor models support multi-task learning, and can be used for a
    variety of tasks, including text classification, sentence similarity, and document retrieval.
    If you want to calculate customized embeddings for specific sentences, you may follow the unified template to write instructions:
        "Represent the `domain` `text_type` for `task_objective`":

        * domain is optional, and it specifies the domain of the text, e.g., science, finance, medicine, etc.
        * text_type is required, and it specifies the encoding unit, e.g., sentence, document, paragraph, etc.
        * task_objective is optional, and it specifies the objective of embedding, e.g., retrieve a document, classify the sentence, etc.

    For example, if you want to calculate embeddings for a document, you may write the instruction as follows:
        "Represent the document for retreival"

    Parameters
    ----------
    name: str
        The name of the model to use. Available models are listed at https://github.com/xlang-ai/instructor-embedding#model-list;
        The default model is hkunlp/instructor-base
    batch_size: int, default 32
        The batch size to use when generating embeddings
    device: str, default "cpu"
        The device to use when generating embeddings
    show_progress_bar: bool, default True
        Whether to show a progress bar when generating embeddings
    normalize_embeddings: bool, default True
        Whether to normalize the embeddings
    quantize: bool, default False
        Whether to quantize the model
    source_instruction: str, default "represent the docuement for retreival"
        The instruction for the source column
    query_instruction: str, default "represent the document for retreiving the most similar documents"
        The instruction for the query

    Examples
    --------
    import lancedb
    from lancedb.pydantic import LanceModel, Vector
    from lancedb.embeddings import get_registry, InstuctorEmbeddingFunction

    instructor = get_registry().get("instructor").create(
                                source_instruction="represent the docuement for retreival",
                                query_instruction="represent the document for retreiving the most similar documents"
                                )

    class Schema(LanceModel):
        vector: Vector(instructor.ndims()) = instructor.VectorField()
        text: str = instructor.SourceField()

    db = lancedb.connect("~/.lancedb")
    tbl = db.create_table("test", schema=Schema, mode="overwrite")

    texts = [{"text": "Capitalism has been dominant in the Western world since the end of feudalism, but most feel[who?] that..."},
            {"text": "The disparate impact theory is especially controversial under the Fair Housing Act because the Act..."},
            {"text": "Disparate impact in United States labor law refers to practices in employment, housing, and other areas that.."}]

    tbl.add(texts)

    """

    name: str = "hkunlp/instructor-base"
    batch_size: int = 32
    device: str = "cpu"
    show_progress_bar: bool = True
    normalize_embeddings: bool = True
    quantize: bool = False
    # convert_to_numpy: bool = True # Hardcoding this as numpy can be ingested directly

    source_instruction: str = "represent the docuement for retreival"
    query_instruction: str = (
        "represent the document for retreiving the most similar documents"
    )

    @weak_lru(maxsize=1)
    def ndims(self):
        model = self.get_model()
        return model.encode("foo").shape[0]

    def compute_query_embeddings(self, query: str, *args, **kwargs) -> List[np.array]:
        return self.generate_embeddings([[self.query_instruction, query]])

    def compute_source_embeddings(self, texts: TEXT, *args, **kwargs) -> List[np.array]:
        texts = self.sanitize_input(texts)
        texts_formatted = []
        for text in texts:
            texts_formatted.append([self.source_instruction, text])
        return self.generate_embeddings(texts_formatted)

    def generate_embeddings(self, texts: List) -> List:
        model = self.get_model()
        res = model.encode(
            texts,
            batch_size=self.batch_size,
            show_progress_bar=self.show_progress_bar,
            normalize_embeddings=self.normalize_embeddings,
        ).tolist()
        return res

    @weak_lru(maxsize=1)
    def get_model(self):
        instructor_embedding = self.safe_import(
            "InstructorEmbedding", "InstructorEmbedding"
        )
        torch = self.safe_import("torch", "torch")

        model = instructor_embedding.INSTRUCTOR(self.name)
        if self.quantize:
            if (
                "qnnpack" in torch.backends.quantized.supported_engines
            ):  # fix for https://github.com/pytorch/pytorch/issues/29327
                torch.backends.quantized.engine = "qnnpack"
            model = torch.quantization.quantize_dynamic(
                model, {torch.nn.Linear}, dtype=torch.qint8
            )
        return model
