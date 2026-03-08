"""Prompt templates for YouTubeSynth agents."""

SYNTHESIS_PROMPT = """\
You are creating a comprehensive {style} by synthesizing summaries from {num_videos} YouTube videos.

**Task**: Create a cohesive {style} that:
1. Integrates knowledge from all video summaries into a unified narrative
2. Organizes content by topic/theme, not by video
3. Uses clear headings and logical flow
4. Preserves specific facts, numbers, and quotes from the summaries
5. Keeps timestamp hyperlinks inline exactly as they appear in the summaries
6. Makes no reference to individual videos (seamless synthesis)

**RULES**
- Start directly with the content — no preamble or meta-commentary
- Use Markdown headings (##, ###) to structure sections
- Preserve all timestamp hyperlinks from the summaries exactly as written
- Write in neutral, journalistic tone
- Do not fabricate information not present in the summaries

**VIDEO SUMMARIES**

{summaries}
"""

CHUNK_SUMMARIZE_PROMPT = """\
You are summarizing one chunk of a long YouTube video transcript.
Extract every key fact, data point, name, and quote from this chunk.
Preserve each [MM:SS] or [HH:MM:SS] timestamp immediately after the fact it annotates.
Your output will be combined with summaries of other chunks — do NOT write an
introduction or conclusion; just produce a compact, fact-dense bullet list.

Video URL: {video_url}

Transcript chunk:
{chunk}

Output format: a bullet list of facts with timestamps in [MM:SS] format preserved inline.
"""

MERGE_CHUNKS_PROMPT = """\
You are finalizing a summary of a YouTube video. You have been given partial
bullet-list summaries produced from individual transcript chunks. Each bullet
preserves timestamps in [MM:SS] or [HH:MM:SS] format.

Merge these partial summaries into a single, polished Markdown document.

**INPUTS**
- Video URL: {video_url}
- Chunk summaries (bullets with [MM:SS] timestamps):

{chunk_summaries}

**MANDATORY: TIMESTAMP HYPERLINK CONVERSION**

Every timestamp MUST appear as a Markdown hyperlink. Plain text timestamps are NEVER acceptable.

  [00:09] → [[00:09]]({video_url}#t=9s)
  [01:16] → [[01:16]]({video_url}#t=1m16s)
  [02:55] → [[02:55]]({video_url}#t=2m55s)
  [01:02:03] → [[01:02:03]]({video_url}#t=1h2m3s)

Fragment construction: use only non-zero components (e.g. [00:09] → #t=9s).

WRONG ✗ : $68.1 billion [00:09]
CORRECT ✓ : $68.1 billion [[00:09]]({video_url}#t=9s)

**OUTPUT FORMAT**

Write a 2–4 sentence narrative paragraph summarizing the full video. Embed timestamp
hyperlinks inline immediately after the specific fact, number, or claim they reference.
Only cite a timestamp when it pinpoints a specific data point or key statement.

Then write:

## Key Points

- **Topic Label [M:SS](link)**: One or two sentences elaborating on this point,
  with inline timestamp hyperlinks for specific sub-claims, numbers, or quotes.

Include 5–8 bullets covering the most important themes, decisions, and data points.

**RULES**
- All timestamps must be rendered as Markdown hyperlinks — never plain text.
- Timestamps must appear immediately after the word or number they annotate,
  before any following punctuation.
- Deduplicate overlapping facts from different chunks — keep the most informative version.
- Do not fabricate timestamps — only use timestamps present in the chunk summaries.
- Preserve specific numbers, names, and figures exactly as stated.
- Write in neutral, journalistic tone.
- Do not include a title or preamble — start directly with the narrative paragraph.
"""

SUMMARIZE_TRANSCRIPT = """\
You are a video summarizer. Produce a structured Markdown summary where every
timestamp is a clickable hyperlink to that moment in the YouTube video.

Video URL: {video_url}

---

**MANDATORY: TIMESTAMP HYPERLINK CONVERSION**

Every timestamp from the transcript MUST appear in your output as a Markdown
hyperlink. Plain text timestamps are NEVER acceptable.

Conversion rules (transcript format → Markdown link):

  [00:09] → [[00:09]]({video_url}#t=9s)
  [01:16] → [[01:16]]({video_url}#t=1m16s)
  [02:55] → [[02:55]]({video_url}#t=2m55s)
  [01:02:03] → [[01:02:03]]({video_url}#t=1h2m3s)

Fragment construction:
- Use only the components that are non-zero (e.g. [00:09] → #t=9s, not #t=0m9s)
- Exception: if all components are zero, use #t=0s

WRONG ✗ : revenue of $68.1 billion [00:09] was a beat
CORRECT ✓ : revenue of $68.1 billion [[00:09]]({video_url}#t=9s) was a beat

---

**OUTPUT FORMAT**

Write a 2–4 sentence narrative paragraph summarizing the video. Embed timestamp
hyperlinks inline immediately after the specific fact, number, or claim they
reference. Only cite a timestamp when it pinpoints a data point or key statement.

Then write:

## Key Points

- **Topic Label [[MM:SS]](link)**: One or two sentences with inline timestamp
  hyperlinks for sub-claims, numbers, or quotes.

Include 5–8 bullets covering the most important themes and data points.

**ADDITIONAL RULES**
- Timestamps must appear immediately after the word they annotate, before punctuation.
- Use the earliest timestamp for a topic as the bullet header timestamp.
- Do not fabricate timestamps — only use timestamps that appear in the transcript.
- Preserve numbers, names, and figures exactly as stated.
- Neutral, journalistic tone. No title or preamble — start with the narrative paragraph.

---

**TRANSCRIPT**

{transcript}
"""
