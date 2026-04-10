"""
Decision Engine - Lidarr-style release evaluation

This module provides a specification-based decision engine for evaluating
releases from indexers against quality profiles and other criteria.

Usage:
    from app.services.decision_engine import DownloadDecisionMaker
    from app.services.decision_engine.specifications import get_default_specifications

    specs = get_default_specifications(db)
    decision_maker = DownloadDecisionMaker(specs)
    decisions = decision_maker.get_decisions(releases, album)
"""
from app.services.decision_engine.decision_maker import DownloadDecisionMaker
from app.services.decision_engine.specifications import (
    IDecisionSpecification,
    get_default_specifications,
)

__all__ = [
    "DownloadDecisionMaker",
    "IDecisionSpecification",
    "get_default_specifications",
]
