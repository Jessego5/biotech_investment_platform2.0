"""
This is the narrative layer, It does not let the model compute or guess anything. 
It takes the facts that analysis.py already worked out from real data and asks 
the model to say them in plain English. The model can only phrase the numbers we 
hand it, it can't invent new ones. if OPENAI_API_KEY is set it uses OpenAI, and 
if neither is set it falls back to a fixed template so the app still works with no
key at all. The keys only come from environment variables.
"""

import os

# a small, cheap OpenAI model. if the API rejects it, swap in a current one.
OPENAI_MODEL = "gpt-4o-mini"

SYSTEM_PROMPT = (
    "You are a careful biotech analyst assistant. You are given a set of facts "
    "that were ALREADY computed from primary sources (ClinicalTrials.gov and SEC "
    "EDGAR). Write a short, plain 2-4 sentence summary for an investor. "
    "STRICT RULES: only use the numbers and facts provided. Never invent or "
    "estimate figures, never add outside knowledge, never give buy/sell advice. "
    "If something isn't in the facts, don't mention it. Keep it neutral and factual."
)


def _facts_to_text(company_name, assessment):
    """Flatten the computed assessment into a plain fact sheet for the model."""
    lines = [f"Company: {company_name}"]

    # add the pipeline signal label and each piece of its evidence
    pipe = assessment.get("pipeline_signal", {})
    lines.append(f"Pipeline signal: {pipe.get('label', 'n/a')}")
    for e in pipe.get("evidence", []):
        lines.append(f"  - {e}")

    # add the financial signal label and its evidence too
    fin = assessment.get("financial_signal", {})
    lines.append(f"Financial signal: {fin.get('label', 'n/a')}")
    for e in fin.get("evidence", []):
        lines.append(f"  - {e}")

    return "\n".join(lines)


def _template_narrative(company_name, assessment):
    """
    No-API-key fallback. Deterministic, still 100% grounded, it just stitches
    the labels together instead of asking a model to phrase them.
    """
    pipe = assessment.get("pipeline_signal", {})
    fin = assessment.get("financial_signal", {})
    # phrase it so it reads cleanly whatever the labels turn out to be (avoids "a advancing")
    return (
        f"On the clinical side, {company_name} reads as: {pipe.get('label', 'n/a')}. "
        f"On the financial side: {fin.get('label', 'n/a')}. The specific trial "
        f"counts and figures behind these signals are shown below."
    )


def _narrate_with_openai(facts):
    from openai import OpenAI
    # the client reads OPENAI_API_KEY straight from the environment
    client = OpenAI()
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        max_tokens=400,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": facts},
        ],
    )
    return resp.choices[0].message.content.strip()


def generate_narrative(company_name, assessment):
    """
    Return a dict: the narrative text plus which source produced it, so the
    frontend can be honest about whether it's real LLM output or the template.
    """
    # flatten the assessment into the plain fact sheet the model will read
    facts = _facts_to_text(company_name, assessment)

    # use OpenAI if its key is set
    if os.environ.get("OPENAI_API_KEY"):
        try:
            return {"source": "openai", "text": _narrate_with_openai(facts)}
        except Exception as e:
            # OpenAI failed, so fall back to the template
            return {"source": "template (openai failed: %s)" % e,
                    "text": _template_narrative(company_name, assessment)}

    # no keys at all, so just use the template so the app still works
    return {"source": "template", "text": _template_narrative(company_name, assessment)}
