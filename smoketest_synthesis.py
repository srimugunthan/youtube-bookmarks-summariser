import asyncio, os
from unittest.mock import AsyncMock
from youtubesynth.agents.synthesis_agent import SynthesisAgent
from youtubesynth.services.gemini_client import GeminiClient

# 1. Write fake per-video summaries
os.makedirs("summaries/smoke_job", exist_ok=True)
with open("summaries/smoke_job/vid001.md", "w") as f:
    f.write("## Summary\n\nPython [[00:10]](https://youtu.be/abc#t=10s) is great for data science.")
with open("summaries/smoke_job/vid002.md", "w") as f:
    f.write("## Summary\n\nFastAPI [[00:05]](https://youtu.be/xyz#t=5s) makes REST APIs simple.")

# 2. Run synthesis
async def main():
    db = AsyncMock()
    token_tracker = AsyncMock()
    token_tracker.record = AsyncMock(return_value=0.0)
    token_tracker.write_report = AsyncMock(return_value={})

    client = GeminiClient(api_key=os.environ["GEMINI_API_KEY"])
    agent = SynthesisAgent(
        db=db,
        token_tracker=token_tracker,
        gemini_client=client,
        style="article",
    )
    result = await agent.synthesize("smoke_job")
    print(result)

asyncio.run(main())
