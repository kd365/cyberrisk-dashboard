curl https://dim0ckdh1dco1.cloudfront.net/api/evaluation/feature-coverage



Interpretation of Feature Coverage Results

{
  "coverage": {
    "analyst_sentiment": {"count": 0, "pct": 0.0},
    "competitive_moat": {"count": 0, "pct": 0.0},
    "cyber_sector_relevance": {"count": 0, "pct": 0.0},
    "executive_events": {"count": 0, "pct": 0.0},
    "guidance_direction": {"count": 0, "pct": 0.0},
    "management_tone": {"count": 0, "pct": 0.0},
    "market_positioning": {"count": 0, "pct": 0.0},
    "vulnerabilities": {"count": 0, "pct": 0.0}
  },
  "total_companies": 30
}
What this means:

You have 30 companies in your database
0% feature coverage - none of the LLM-derived features have been populated yet
The 8 features tracked are:
analyst_sentiment - Sentiment from analyst reports
competitive_moat - Company's competitive advantages
cyber_sector_relevance - How relevant to cybersecurity sector
executive_events - Leadership changes, M&A, etc.
guidance_direction - Forward guidance trends
management_tone - Tone from earnings calls
market_positioning - Market position assessment
vulnerabilities - Known security vulnerabilities
This is expected - the LLM features need to be extracted from your documents using the knowledge graph / Neo4j queries. The feature evaluation service reads from the graph, but the data hasn't been populated yet.

Other Evaluation Endpoints
1. Feature Importance (GET):


curl "https://dim0ckdh1dco1.cloudfront.net/api/evaluation/feature-importance?tickers=AAPL,MSFT,GOOGL"
2. Ablation Study (POST) - This is the main evaluation endpoint:


curl -X POST "https://dim0ckdh1dco1.cloudfront.net/api/evaluation/ablation-study" \
  -H "Content-Type: application/json" \
  -d '{
    "tickers": ["AAPL", "MSFT", "GOOGL"],
    "days_forward": 30,
    "target_threshold": 0.02,
    "cv_folds": 5
  }'
Parameters for ablation study:

tickers - List of stock tickers to evaluate (optional, defaults to all)
days_forward - Days ahead for return prediction (default: 30)
target_threshold - Return threshold for binary classification (default: 0.02 = 2%)
cv_folds - Cross-validation folds (default: 5)
The ablation study compares model performance with and without LLM features to measure their "lift" - but since feature coverage is 0%, you'll need to populate the knowledge graph first before this will show meaningful results.