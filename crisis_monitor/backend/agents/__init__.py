"""
agents/ — All LLM agents for Crisis Monitor pipeline

Execution order:
  00 - ScannerAgent    (bootstrap + weekly web search)
  01 - GNewsCollector  (enricher: news collection)
  02 - ClassifierAgent (enricher: article classification)
  03 - MatcherAgent    (enricher: event-to-crisis matching)
  04 - ConnectorAgent  (enricher: country connections)
  05 - AnalystAgent    (daily: deep analysis, Sonnet)
  06 - VerifierAgent   (daily: monthly status verification)
"""

from agents.base_agent import BaseAgent
from agents.agent_00_scanner import ScannerAgent
from agents.agent_01_collector import GNewsCollector
from agents.agent_02_classifier import ClassifierAgent
from agents.agent_03_matcher import MatcherAgent
from agents.agent_04_connector import ConnectorAgent
from agents.agent_05_analyst import AnalystAgent
from agents.agent_06_verifier import VerifierAgent
