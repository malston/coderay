"""Codebase Knowledge Builder pipeline."""
from pocketflow import Flow
from nodes import SmartCrawl, Analyze, Relate, WriteChapters


def create_tour_flow() -> Flow:
    crawl = SmartCrawl()
    analyze = Analyze()
    relate = Relate()
    write = WriteChapters()

    crawl >> analyze >> relate >> write
    return Flow(start=crawl)
