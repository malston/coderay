"""Codebase Knowledge Builder pipeline."""
from pocketflow import Flow
from crawl.analyses.tour.nodes import Analyze, ExtractGraph, Relate, SmartCrawl, WriteChapters


def create_tour_flow() -> Flow:
    crawl = SmartCrawl()
    extract_graph = ExtractGraph()
    analyze = Analyze()
    relate = Relate()
    write = WriteChapters()

    crawl >> extract_graph >> analyze >> relate >> write
    return Flow(start=crawl)
