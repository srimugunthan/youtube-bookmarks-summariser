import argparse


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="youtubesynth",
        description="YouTubeSynth — summarise and synthesise YouTube video transcripts.",
    )
    args = parser.parse_args()  # noqa: F841
    print("YouTubeSynth stub — full implementation coming in Phase 8.")


if __name__ == "__main__":
    main()
