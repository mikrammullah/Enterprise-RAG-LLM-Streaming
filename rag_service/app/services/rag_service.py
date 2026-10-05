import json
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import DocumentChunk
from app.schemas import DocumentSource, IngestResponse, QueryResponse
from app.services.chunking import split_text
from app.services.providers import ModelProvider
from app.telemetry import telemetry


class RAGService:
    def __init__(self, session: AsyncSession, settings: Settings):
        self.session = session
        self.settings = settings
        self.models = ModelProvider(settings)

    async def ingest(
        self, tenant_id: str, filename: str, content: str, metadata: dict | None = None
    ) -> IngestResponse:
        async with telemetry.track("chunk"):
            chunks = split_text(content, self.settings.chunk_size, self.settings.chunk_overlap)
        if not chunks:
            raise ValueError("The uploaded document contains no extractable text")
        document_id = uuid4()
        async with telemetry.track("embed"):
            vectors = await self.models.embed(chunks)
        async with telemetry.track("index"):
            self.session.add_all(
                [
                    DocumentChunk(
                        tenant_id=tenant_id,
                        document_id=document_id,
                        filename=filename,
                        chunk_index=index,
                        content=chunk,
                        metadata_json=metadata or {},
                        embedding=vector,
                    )
                    for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))
                ]
            )
            await self.session.commit()
        return IngestResponse(document_id=document_id, filename=filename, chunks_created=len(chunks))

    async def delete_document(self, tenant_id: str, document_id: UUID) -> bool:
        result = await self.session.execute(
            delete(DocumentChunk).where(
                DocumentChunk.tenant_id == tenant_id,
                DocumentChunk.document_id == document_id,
            )
        )
        await self.session.commit()
        return bool(result.rowcount)

    async def _retrieve(
        self, tenant_id: str, query: str, top_k: int
    ) -> list[tuple[DocumentChunk, float]]:
        async with telemetry.track("query_embed"):
            query_vector = (await self.models.embed([query]))[0]
        async with telemetry.track("retrieve"):
            distance = DocumentChunk.embedding.cosine_distance(query_vector)
            statement = (
                select(DocumentChunk, distance.label("distance"))
                .where(DocumentChunk.tenant_id == tenant_id)
                .order_by(distance)
                .limit(top_k)
            )
            rows = (await self.session.execute(statement)).all()
        return [(row[0], max(0.0, 1.0 - float(row[1]))) for row in rows]

    @staticmethod
    def _sources(rows: list[tuple[DocumentChunk, float]]) -> list[DocumentSource]:
        return [
            DocumentSource(
                document_id=chunk.document_id,
                filename=chunk.filename,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                metadata=chunk.metadata_json,
                score=score,
            )
            for chunk, score in rows
        ]

    async def query(self, tenant_id: str, query: str, top_k: int) -> QueryResponse:
        rows = await self._retrieve(tenant_id, query, top_k)
        contexts = [chunk.content for chunk, _ in rows]
        async with telemetry.track("generate"):
            answer = await self.models.answer(query, contexts)
        return QueryResponse(answer=answer, sources=self._sources(rows))

    async def stream(self, tenant_id: str, query: str, top_k: int) -> AsyncIterator[str]:
        rows = await self._retrieve(tenant_id, query, top_k)
        sources = [source.model_dump(mode="json") for source in self._sources(rows)]
        yield f"event: sources\ndata: {json.dumps({'sources': sources})}\n\n"
        async with telemetry.track("stream"):
            async for token in self.models.stream_answer(query, [chunk.content for chunk, _ in rows]):
                yield f"data: {json.dumps({'token': token})}\n\n"
        yield "event: done\ndata: {}\n\n"
