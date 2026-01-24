#!/usr/bin/env python3
"""
CyberRisk Agent Test Script
============================
Tests the LangChain agent with a series of questions to verify:
- Tool usage (14 tools available)
- Mem0 semantic memory
- PostgreSQL session memory
- Response quality

Usage:
    python scripts/test_agent.py [--api-url URL] [--email EMAIL]

Examples:
    # Test against local backend
    python scripts/test_agent.py --api-url http://localhost:5000

    # Test against production
    python scripts/test_agent.py --api-url https://dim0ckdh1dco1.cloudfront.net
"""

import argparse
import json
import requests
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional

# ANSI colors for terminal output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


# Test questions organized by category
TEST_QUESTIONS = [
    # Category 1: Company Information (should use get_company_info, get_companies)
    {
        "question": "What companies do you track?",
        "category": "Company Info",
        "expected_tools": ["get_companies"],
        "notes": "Should list all 30+ tracked cybersecurity companies"
    },
    {
        "question": "Tell me about CrowdStrike's business model",
        "category": "Company Info",
        "expected_tools": ["get_company_info"],
        "notes": "Should describe CRWD's endpoint security business"
    },

    # Category 2: Sentiment Analysis (should use get_sentiment)
    {
        "question": "What's the sentiment for PANW?",
        "category": "Sentiment",
        "expected_tools": ["get_sentiment"],
        "notes": "Should return AWS Comprehend sentiment analysis"
    },

    # Category 3: Forecasting (should use get_forecast)
    {
        "question": "What's the price forecast for CrowdStrike?",
        "category": "Forecast",
        "expected_tools": ["get_forecast"],
        "notes": "Should return Prophet model predictions"
    },

    # Category 4: Growth Analytics (should use get_growth)
    {
        "question": "Show me employee growth data for Zscaler",
        "category": "Growth",
        "expected_tools": ["get_growth"],
        "notes": "Should return CoreSignal employee/hiring data"
    },

    # Category 5: Knowledge Graph - Executive Events (should use get_executive_events)
    {
        "question": "What executive changes have happened at Fortinet?",
        "category": "Knowledge Graph",
        "expected_tools": ["get_executive_events"],
        "notes": "Should query Neo4j HAS_EXECUTIVE_EVENT relationships"
    },

    # Category 6: Knowledge Graph - Vulnerabilities (should use get_vulnerabilities)
    {
        "question": "What vulnerabilities affect Palo Alto Networks products?",
        "category": "Knowledge Graph",
        "expected_tools": ["get_vulnerabilities"],
        "notes": "Should query Neo4j HAS_VULNERABILITY relationships"
    },

    # Category 7: Knowledge Graph - Patents (should use get_patents)
    {
        "question": "What patents has CrowdStrike filed?",
        "category": "Knowledge Graph",
        "expected_tools": ["get_patents"],
        "notes": "Should query Neo4j FILED relationships to Patent nodes"
    },

    # Category 8: SEC Filings (should use search_filings)
    {
        "question": "What are the main risks mentioned in Okta's latest 10-K?",
        "category": "SEC Filings",
        "expected_tools": ["search_filings"],
        "notes": "Should search SEC filings for risk factors"
    },

    # Category 9: Earnings (should use get_earnings_summary)
    {
        "question": "Summarize CrowdStrike's latest earnings call",
        "category": "Earnings",
        "expected_tools": ["get_earnings_summary"],
        "notes": "Should return earnings transcript summary"
    },

    # Category 10: Comparison (should use multiple tools)
    {
        "question": "Compare Palo Alto Networks and Fortinet in terms of sentiment and growth",
        "category": "Comparison",
        "expected_tools": ["get_sentiment", "get_growth"],
        "notes": "Should call tools for both tickers"
    },

    # Category 11: Memory Test - Set preference
    {
        "question": "I'm particularly interested in CrowdStrike and endpoint security companies",
        "category": "Memory",
        "expected_tools": [],
        "notes": "Should be stored in Mem0 for later recall"
    },

    # Category 12: Memory Test - Recall preference
    {
        "question": "Based on my interests, which companies should I focus on?",
        "category": "Memory Recall",
        "expected_tools": [],
        "notes": "Should recall CrowdStrike interest from Mem0"
    },

    # Category 13: Dashboard Help
    {
        "question": "How do I use this dashboard?",
        "category": "Help",
        "expected_tools": [],
        "notes": "Should provide dashboard usage guidance"
    },

    # Category 14: Complex Query
    {
        "question": "Which cybersecurity company has the best combination of positive sentiment and high growth?",
        "category": "Analysis",
        "expected_tools": ["get_companies", "get_sentiment", "get_growth"],
        "notes": "Should analyze multiple companies"
    },
]


class AgentTester:
    """Test harness for the CyberRisk LangChain agent."""

    def __init__(self, api_url: str, user_email: str, verbose: bool = True):
        self.api_url = api_url.rstrip('/')
        self.user_email = user_email
        self.session_id = f"test_{uuid.uuid4().hex[:8]}"
        self.verbose = verbose
        self.results: List[Dict] = []

    def log(self, message: str, color: str = ""):
        """Print colored log message."""
        if self.verbose:
            print(f"{color}{message}{Colors.ENDC}")

    def chat(self, message: str) -> Dict:
        """Send a chat message to the agent."""
        url = f"{self.api_url}/api/chat"
        payload = {
            "message": message,
            "session_id": self.session_id,
            "user_email": self.user_email
        }

        try:
            response = requests.post(url, json=payload, timeout=60)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"error": str(e), "response": None}

    def run_test(self, test: Dict, index: int) -> Dict:
        """Run a single test question."""
        self.log(f"\n{'='*70}", Colors.BLUE)
        self.log(f"Test {index + 1}/{len(TEST_QUESTIONS)}: {test['category']}", Colors.BOLD)
        self.log(f"{'='*70}", Colors.BLUE)
        self.log(f"\n{Colors.CYAN}Question:{Colors.ENDC} {test['question']}")
        self.log(f"{Colors.YELLOW}Expected tools:{Colors.ENDC} {test['expected_tools']}")

        start_time = time.time()
        result = self.chat(test["question"])
        elapsed = time.time() - start_time

        # Parse result
        test_result = {
            "question": test["question"],
            "category": test["category"],
            "expected_tools": test["expected_tools"],
            "notes": test["notes"],
            "elapsed_seconds": round(elapsed, 2),
            "success": False,
            "response": None,
            "tools_used": [],
            "semantic_memory_used": False,
            "error": None
        }

        if "error" in result and result.get("response") is None:
            test_result["error"] = result["error"]
            self.log(f"\n{Colors.RED}ERROR: {result['error']}{Colors.ENDC}")
        else:
            test_result["success"] = True
            test_result["response"] = result.get("response", "")[:500]  # Truncate for display
            test_result["tools_used"] = result.get("tools_used", [])
            test_result["semantic_memory_used"] = result.get("semantic_memory_used", False)

            # Display response
            response_text = result.get("response", "No response")
            self.log(f"\n{Colors.GREEN}Response:{Colors.ENDC}")
            # Truncate long responses
            if len(response_text) > 500:
                self.log(f"  {response_text[:500]}...")
            else:
                self.log(f"  {response_text}")

            # Display metadata
            self.log(f"\n{Colors.CYAN}Metadata:{Colors.ENDC}")
            self.log(f"  Tools used: {test_result['tools_used']}")
            self.log(f"  Semantic memory: {test_result['semantic_memory_used']}")
            self.log(f"  Response time: {elapsed:.2f}s")

            # Check expected tools
            expected = set(test["expected_tools"])
            actual = set(test_result["tools_used"])
            if expected and expected.issubset(actual):
                self.log(f"  {Colors.GREEN}✓ Expected tools used{Colors.ENDC}")
            elif expected and not actual:
                self.log(f"  {Colors.YELLOW}⚠ No tools used (expected: {expected}){Colors.ENDC}")
            elif expected:
                missing = expected - actual
                self.log(f"  {Colors.YELLOW}⚠ Missing tools: {missing}{Colors.ENDC}")

        return test_result

    def run_all_tests(self) -> Dict:
        """Run all test questions and return summary."""
        self.log(f"\n{'#'*70}", Colors.HEADER)
        self.log(f"# CyberRisk Agent Test Suite", Colors.HEADER)
        self.log(f"# API: {self.api_url}", Colors.HEADER)
        self.log(f"# User: {self.user_email}", Colors.HEADER)
        self.log(f"# Session: {self.session_id}", Colors.HEADER)
        self.log(f"# Time: {datetime.now().isoformat()}", Colors.HEADER)
        self.log(f"{'#'*70}", Colors.HEADER)

        for i, test in enumerate(TEST_QUESTIONS):
            result = self.run_test(test, i)
            self.results.append(result)
            # Small delay between requests
            time.sleep(1)

        return self.generate_summary()

    def generate_summary(self) -> Dict:
        """Generate test summary."""
        total = len(self.results)
        passed = sum(1 for r in self.results if r["success"])
        failed = total - passed

        # Count tool usage
        all_tools = []
        for r in self.results:
            all_tools.extend(r.get("tools_used", []))
        tool_counts = {}
        for tool in all_tools:
            tool_counts[tool] = tool_counts.get(tool, 0) + 1

        # Count memory usage
        memory_used = sum(1 for r in self.results if r.get("semantic_memory_used"))

        # Average response time
        avg_time = sum(r["elapsed_seconds"] for r in self.results) / total if total > 0 else 0

        summary = {
            "total_tests": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": f"{(passed/total)*100:.1f}%" if total > 0 else "0%",
            "avg_response_time": f"{avg_time:.2f}s",
            "tool_usage": tool_counts,
            "unique_tools_used": len(tool_counts),
            "semantic_memory_hits": memory_used,
            "session_id": self.session_id,
            "timestamp": datetime.now().isoformat()
        }

        # Print summary
        self.log(f"\n{'='*70}", Colors.HEADER)
        self.log(f"TEST SUMMARY", Colors.BOLD)
        self.log(f"{'='*70}", Colors.HEADER)
        self.log(f"\n{Colors.GREEN}Passed: {passed}/{total} ({summary['pass_rate']}){Colors.ENDC}")
        if failed > 0:
            self.log(f"{Colors.RED}Failed: {failed}/{total}{Colors.ENDC}")
        self.log(f"\n{Colors.CYAN}Performance:{Colors.ENDC}")
        self.log(f"  Average response time: {summary['avg_response_time']}")
        self.log(f"\n{Colors.CYAN}Tool Usage ({summary['unique_tools_used']} unique tools):{Colors.ENDC}")
        for tool, count in sorted(tool_counts.items(), key=lambda x: -x[1]):
            self.log(f"  {tool}: {count} calls")
        self.log(f"\n{Colors.CYAN}Memory:{Colors.ENDC}")
        self.log(f"  Semantic memory used in {memory_used} responses")

        # List failures
        failures = [r for r in self.results if not r["success"]]
        if failures:
            self.log(f"\n{Colors.RED}Failed Tests:{Colors.ENDC}")
            for f in failures:
                self.log(f"  - {f['category']}: {f['error']}")

        return summary

    def save_results(self, filepath: str):
        """Save results to JSON file."""
        output = {
            "summary": self.generate_summary(),
            "results": self.results
        }
        with open(filepath, 'w') as f:
            json.dump(output, f, indent=2)
        self.log(f"\n{Colors.GREEN}Results saved to: {filepath}{Colors.ENDC}")


def main():
    parser = argparse.ArgumentParser(description="Test CyberRisk LangChain Agent")
    parser.add_argument(
        "--api-url",
        default="http://localhost:5000",
        help="API base URL (default: http://localhost:5000)"
    )
    parser.add_argument(
        "--email",
        default="kathleen@khilldata.dev",
        help="User email for memory isolation (default: kathleen@khilldata.dev)"
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output JSON file for results"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Reduce output verbosity"
    )

    args = parser.parse_args()

    # Create tester
    tester = AgentTester(
        api_url=args.api_url,
        user_email=args.email,
        verbose=not args.quiet
    )

    # Run tests
    try:
        summary = tester.run_all_tests()

        # Save results if output file specified
        if args.output:
            tester.save_results(args.output)
        else:
            # Default output file
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"agent_test_results_{timestamp}.json"
            tester.save_results(output_file)

        # Exit code based on failures
        if summary["failed"] > 0:
            return 1
        return 0

    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Test interrupted by user{Colors.ENDC}")
        return 130
    except Exception as e:
        print(f"\n{Colors.RED}Error: {e}{Colors.ENDC}")
        return 1


if __name__ == "__main__":
    exit(main())
