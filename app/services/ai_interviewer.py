import json
import re
from typing import Any, Dict, List, Optional

from openai import OpenAI

from ..config import settings
from ..models import Candidate, CandidateProfile, InterviewTranscript, JobDescription, Resume


SCORE_METRICS = [
    {"category": "Technical Depth", "weight": 0.20},
    {"category": "Applied Problem Solving", "weight": 0.15},
    {"category": "System Design & Trade-offs", "weight": 0.12},
    {"category": "Role & Domain Fit", "weight": 0.12},
    {"category": "Ownership & Leadership", "weight": 0.12},
    {"category": "Collaboration & Stakeholder Handling", "weight": 0.10},
    {"category": "Communication Clarity", "weight": 0.10},
    {"category": "Adaptability & Learning", "weight": 0.05},
    {"category": "Motivation & Company Fit", "weight": 0.04},
]

QUESTION_PLAN = [
    {
        "category": "background",
        "difficulty": "easy",
        "focus": "professional introduction, current role, strongest recent work, and interview expectations",
        "fallback": "Hello, I am Maya, your AI interviewer for today. I will ask a mix of role-specific, technical, problem-solving, leadership, collaboration, and company-fit questions. To begin, please walk me through your current role and the work you are most proud of.",
    },
    {
        "category": "technical_depth",
        "difficulty": "medium",
        "focus": "role-specific technical depth from the job description and resume",
        "fallback": "Let us go deeper technically. Which core technical skill required for this role is your strongest, and can you explain a real implementation where you used it?",
    },
    {
        "category": "problem_solving",
        "difficulty": "medium",
        "focus": "debugging, structured thinking, root cause analysis, and outcome",
        "fallback": "Tell me about a difficult technical problem you solved recently. What was the root cause, what options did you consider, and what result did you achieve?",
    },
    {
        "category": "system_design",
        "difficulty": "hard",
        "focus": "architecture, scalability, reliability, data flow, and trade-offs",
        "fallback": "Imagine you need to design a reliable feature for this role that handles growth over time. How would you structure the system, and what trade-offs would you make?",
    },
    {
        "category": "role_domain_fit",
        "difficulty": "medium",
        "focus": "fit against company, domain, job responsibilities, and expected day-to-day work",
        "fallback": "Looking at this role and company context, which responsibility do you think will matter most in the first month, and how would you approach it?",
    },
    {
        "category": "ownership_leadership",
        "difficulty": "medium",
        "focus": "ownership, leadership, decision-making, mentoring, and accountability",
        "fallback": "Describe a time you owned a piece of work end to end or led others through ambiguity. What decisions did you make, and what changed because of your leadership?",
    },
    {
        "category": "collaboration",
        "difficulty": "medium",
        "focus": "stakeholder communication, conflict resolution, cross-functional work",
        "fallback": "Tell me about a time you worked with a difficult stakeholder or teammate. How did you keep the work moving without damaging the relationship?",
    },
    {
        "category": "adaptability",
        "difficulty": "medium",
        "focus": "learning speed, feedback, resilience, and changing requirements",
        "fallback": "Give me an example of a time the requirements changed late or you received difficult feedback. How did you adapt?",
    },
    {
        "category": "motivation_company_fit",
        "difficulty": "easy",
        "focus": "motivation for the role, company fit, working style, and career direction",
        "fallback": "Why does this role at this company make sense for your next step, and what kind of team environment helps you do your best work?",
    },
    {
        "category": "candidate_questions",
        "difficulty": "easy",
        "focus": "give the candidate room to ask questions about the role, company, team, process, or expectations only",
        "fallback": "Before we close, what questions do you have about the role, company, team, interview process, or expectations? Please keep them within this hiring conversation so the recruiter can follow up clearly.",
    },
]

TECHNICAL_WORDS = {
    "api", "architecture", "database", "sql", "python", "react", "next", "node", "fastapi", "backend", "frontend",
    "cache", "queue", "latency", "scalability", "testing", "deployment", "aws", "docker", "kubernetes", "microservice",
    "security", "authentication", "authorization", "algorithm", "data", "schema", "performance", "monitoring",
}
LEADERSHIP_WORDS = {"led", "lead", "owned", "ownership", "mentored", "guided", "coordinated", "decision", "accountable"}
COLLABORATION_WORDS = {"stakeholder", "team", "collaborated", "aligned", "communicated", "conflict", "manager", "client"}
OUTCOME_WORDS = {"reduced", "improved", "increased", "saved", "launched", "delivered", "measured", "impact", "result"}


def _client() -> Optional[OpenAI]:
    if not settings.openai_api_key:
        return None
    return OpenAI(api_key=settings.openai_api_key, timeout=18.0, max_retries=0)


def _profile_context(profile: Optional[CandidateProfile]) -> str:
    if not profile:
        return "Candidate profile is not completed yet."
    return f"""
Current CTC: {profile.current_ctc}
Expected CTC: {profile.expected_ctc}
Notice Period: {profile.notice_period}
Current Location: {profile.current_location}
LinkedIn: {profile.linkedin_url or "N/A"}
Portfolio: {profile.portfolio_url or "N/A"}
"""


def _job_context(job: JobDescription) -> str:
    return f"""
Job Title: {job.job_title}
Company: {job.company_name}
Department: {job.department}
Experience Required: {job.experience_required}
Location: {job.location}
Employment Type: {job.employment_type}
Skills Required: {job.skills_required}
Responsibilities: {job.responsibilities}
Full JD: {job.full_job_description}
"""


def _transcript_context(transcripts: List[InterviewTranscript]) -> str:
    if not transcripts:
        return "No questions have been asked yet."
    lines = []
    for item in transcripts:
        lines.append(f"Q{item.sequence_number}: {item.question_text}")
        lines.append(f"A{item.sequence_number}: {item.answer_text or '[not answered yet]'}")
    return "\n".join(lines)


def _planned_step(sequence: int, max_questions: int) -> Dict[str, str]:
    if sequence >= max_questions:
        return QUESTION_PLAN[-1]
    assessed_plan = QUESTION_PLAN[:-1]
    if max_questions >= len(QUESTION_PLAN):
        return assessed_plan[min(sequence - 1, len(assessed_plan) - 1)]
    if max_questions <= 2:
        return assessed_plan[min(sequence - 1, len(assessed_plan) - 1)]
    plan_index = int(((sequence - 1) / max(1, max_questions - 2)) * (len(assessed_plan) - 1))
    return assessed_plan[min(plan_index, len(assessed_plan) - 1)]


def _fallback_question(job: JobDescription, sequence: int, max_questions: int) -> Dict[str, str]:
    step = _planned_step(sequence, max_questions)
    text = step["fallback"]
    if sequence == 2 and job.skills_required:
        text = f"Let us go deeper technically. From these required skills, {job.skills_required}, which one have you used most deeply, and what exactly did you build with it?"
    return {"question": text, "category": step["category"], "difficulty": step["difficulty"]}


def _answer_words(answer: Optional[str]) -> List[str]:
    return re.findall(r"[a-zA-Z0-9+#.]+", (answer or "").lower())


def _quality_score(answer: Optional[str], *, require_words: Optional[set[str]] = None) -> tuple[int, str]:
    words = _answer_words(answer)
    if not words:
        return 1, "No answer was provided."

    unique_ratio = len(set(words)) / max(1, len(words))
    answer_text = " ".join(words)
    score = 1
    evidence = []

    if len(words) >= 12:
        score += 1
        evidence.append("has a minimal explanation")
    if len(words) >= 35:
        score += 1
        evidence.append("adds useful detail")
    if len(words) >= 70:
        score += 1
        evidence.append("is detailed")
    if any(word in answer_text for word in OUTCOME_WORDS):
        score += 1
        evidence.append("mentions impact")
    if re.search(r"\b\d+%?|\b(first|second|third)\b", answer_text):
        score += 1
        evidence.append("includes measurable or ordered detail")
    if any(word in answer_text for word in TECHNICAL_WORDS):
        score += 1
        evidence.append("contains technical evidence")
    if any(word in answer_text for word in LEADERSHIP_WORDS):
        score += 1
        evidence.append("shows ownership")
    if any(word in answer_text for word in COLLABORATION_WORDS):
        score += 1
        evidence.append("shows collaboration context")

    if unique_ratio < 0.42 or len(words) < 8:
        score = min(score, 3)
        evidence.append("answer is too short or repetitive")
    if require_words and not any(word in answer_text for word in require_words):
        score = min(score, 4)
        evidence.append("lacks required evidence for this competency")

    return max(1, min(10, score)), "; ".join(evidence) or "limited evidence"


def _metric_score(metric: str, transcripts: List[InterviewTranscript]) -> Dict[str, Any]:
    usable = [item for item in transcripts if item.answer_text and item.category != "candidate_questions"]
    if not usable:
        return {"category": metric, "score": 1, "reasoning": "No assessable answers were submitted."}

    category_answers = {
        "Technical Depth": ("technical_depth", TECHNICAL_WORDS),
        "Applied Problem Solving": ("problem_solving", OUTCOME_WORDS),
        "System Design & Trade-offs": ("system_design", TECHNICAL_WORDS),
        "Role & Domain Fit": ("role_domain_fit", None),
        "Ownership & Leadership": ("ownership_leadership", LEADERSHIP_WORDS),
        "Collaboration & Stakeholder Handling": ("collaboration", COLLABORATION_WORDS),
        "Communication Clarity": ("", None),
        "Adaptability & Learning": ("adaptability", None),
        "Motivation & Company Fit": ("motivation_company_fit", None),
    }
    category, required_words = category_answers.get(metric, ("", None))
    relevant = [item for item in usable if item.category == category] if category else usable
    if not relevant:
        relevant = usable

    scored = [_quality_score(item.answer_text, require_words=required_words) for item in relevant]
    score = int(round(sum(item[0] for item in scored) / len(scored)))
    if metric == "Communication Clarity":
        score = int(round(sum(_quality_score(item.answer_text)[0] for item in usable) / len(usable)))
    reasoning = scored[0][1]
    return {"category": metric, "score": max(1, min(10, score)), "reasoning": reasoning}


def _strict_scorecard(transcripts: List[InterviewTranscript], model_scores: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    model_by_category = {str(item.get("category", "")).lower(): item for item in (model_scores or [])}
    scorecard = []
    for metric in SCORE_METRICS:
        category = metric["category"]
        strict = _metric_score(category, transcripts)
        model = model_by_category.get(category.lower())
        if model:
            try:
                model_score = max(1, min(10, int(model.get("score", strict["score"]))))
            except (TypeError, ValueError):
                model_score = strict["score"]
            strict["score"] = min(model_score, strict["score"] + 1)
            if model.get("reasoning"):
                strict["reasoning"] = f"{model.get('reasoning')} Strict cap: {strict['reasoning']}"
        strict["weight"] = metric["weight"]
        scorecard.append(strict)
    return scorecard


def _weighted_overall(scores: List[Dict[str, Any]]) -> int:
    total = 0.0
    weight_total = 0.0
    for score in scores:
        weight = float(score.get("weight", 0.0) or 0.0)
        value = max(1, min(10, int(score.get("score", 1))))
        total += value * weight
        weight_total += weight
    if not weight_total:
        return 0
    return int(round((total / weight_total) * 10))


def _recommendation_from_score(overall: int) -> str:
    if overall >= 88:
        return "Strong Hire"
    if overall >= 75:
        return "Hire"
    if overall >= 62:
        return "Borderline"
    if overall >= 45:
        return "No Hire"
    return "Strong No Hire"


def generate_next_question(
    *,
    candidate: Candidate,
    job: JobDescription,
    profile: Optional[CandidateProfile],
    resume: Optional[Resume],
    transcripts: List[InterviewTranscript],
    max_questions: int,
) -> Dict[str, str]:
    sequence = len(transcripts) + 1
    planned = _planned_step(sequence, max_questions)
    fallback = _fallback_question(job, sequence, max_questions)

    client = _client()
    if not client:
        return fallback

    system_prompt = """You are Maya, a professional AI human interviewer visible on video.
You must behave like a calm recruiter or hiring manager, not like a robot or script reader.
Ask exactly one question at a time. Questions must evolve from the candidate's previous answers, but must follow the target competency below.
Use JD context, resume context, candidate profile, and transcript history.
The interview must be a 15 minute structured mix across technical depth, problem solving, system design, role/domain fit, leadership, collaboration, adaptability, motivation, and candidate questions.
Adjust difficulty based on answer depth.
The first question must include a brief professional introduction and interview process explanation.
When target category is technical_depth, problem_solving, or system_design, ask a real technical question tied to the job/resume. Do not ask a generic HR question.
When target category is candidate_questions, only invite questions about the company, role, team, interview process, or expectations. Do not go outside this hiring scope.
Return only JSON in this shape:
{"question":"...","category":"background|technical_depth|problem_solving|system_design|role_domain_fit|ownership_leadership|collaboration|adaptability|motivation_company_fit|candidate_questions","difficulty":"easy|medium|hard"}
"""
    user_prompt = f"""
Question number: {sequence} of {max_questions}
Target category: {planned["category"]}
Target difficulty: {planned["difficulty"]}
Target focus: {planned["focus"]}

Candidate:
Name: {candidate.full_name}
Email: {candidate.email}
Mobile: {candidate.mobile_number}
Current Role: {candidate.current_role}
Current Company: {candidate.current_company or "N/A"}

Job:
{_job_context(job)}

Candidate Profile:
{_profile_context(profile)}

Resume Text:
{(resume.parsed_text if resume and resume.parsed_text else "Resume text unavailable")[:12000]}

Transcript so far:
{_transcript_context(transcripts)}
"""
    try:
        response = client.chat.completions.create(
            model=settings.openai_chat_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.55,
            response_format={"type": "json_object"},
        )
    except Exception:
        return fallback
    try:
        parsed = json.loads(response.choices[0].message.content or "{}")
    except json.JSONDecodeError:
        parsed = {}
    return {
        "question": parsed.get("question") or fallback["question"],
        "category": planned["category"],
        "difficulty": parsed.get("difficulty") or planned["difficulty"],
    }


def generate_report(
    *,
    candidate: Candidate,
    job: JobDescription,
    profile: Optional[CandidateProfile],
    resume: Optional[Resume],
    transcripts: List[InterviewTranscript],
) -> Dict[str, Any]:
    transcript = _transcript_context(transcripts)
    strict_scores = _strict_scorecard(transcripts)
    strict_overall = _weighted_overall(strict_scores)
    strict_recommendation = _recommendation_from_score(strict_overall)

    fallback = {
        "summary": f"{candidate.full_name} completed the AI human interviewer screening for {job.job_title}.",
        "strengths": "Strengths require recruiter review because the AI report used evidence-based fallback scoring.",
        "weaknesses": "Weak or generic answers are penalized. Missing evidence lowers technical, leadership, and problem-solving scores.",
        "key_observations": "Scorecard is based on answer specificity, role relevance, technical evidence, ownership, collaboration, and measurable outcomes.",
        "technical_assessment": "Technical score is capped when answers lack concrete implementation detail, architecture, tools, trade-offs, or debugging evidence.",
        "behavioral_assessment": "Behavioral score is based on concrete examples of ownership, collaboration, feedback, and adaptability.",
        "recommendation": strict_recommendation,
        "recommendation_reason": f"Evidence-based fallback score: {strict_overall}/100. Random, short, or generic answers are capped low.",
        "scores": strict_scores,
        "overall_score": strict_overall,
    }

    client = _client()
    if not client:
        return fallback

    metric_lines = "\n".join(f"- {item['category']} ({int(item['weight'] * 100)}%)" for item in SCORE_METRICS)
    system_prompt = f"""You are a strict senior hiring manager generating a detailed hiring report.
Score only from transcript evidence. Do not reward confidence, fluency, or long answers unless they contain specific, role-relevant evidence.
If an answer is random, vague, off-topic, repetitive, or lacks examples, score that competency 1-3.
If an answer is generic but somewhat relevant, score 4-5.
Only score 7+ when the candidate gives concrete examples, technical details, trade-offs, decisions, and outcomes.
Only score 9-10 for exceptional, detailed, role-specific evidence.
The final overall score must reflect this weighted scorecard:
{metric_lines}
Recommendation must be one of: Strong Hire, Hire, Borderline, No Hire, Strong No Hire.
Mention coverage gaps, including if no real technical answer was given.
Candidate questions at the end should be treated as closing context, not as proof of technical ability.
Return only JSON:
{{
  "summary": "...",
  "strengths": "...",
  "weaknesses": "...",
  "key_observations": "...",
  "technical_assessment": "...",
  "behavioral_assessment": "...",
  "recommendation": "...",
  "recommendation_reason": "...",
  "scores": [{{"category":"Technical Depth","score":1,"reasoning":"..."}}]
}}
"""
    user_prompt = f"""
Candidate:
{candidate.full_name}, {candidate.current_role}, {candidate.current_company or "N/A"}

Job:
{_job_context(job)}

Profile:
{_profile_context(profile)}

Resume:
{(resume.parsed_text if resume and resume.parsed_text else "Resume text unavailable")[:12000]}

Interview Transcript:
{transcript}
"""
    try:
        response = client.chat.completions.create(
            model=settings.openai_chat_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.15,
            response_format={"type": "json_object"},
        )
    except Exception:
        return fallback
    content = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = fallback
    parsed["scores"] = _strict_scorecard(transcripts, parsed.get("scores"))
    parsed["overall_score"] = _weighted_overall(parsed["scores"])
    parsed["recommendation"] = _recommendation_from_score(parsed["overall_score"])
    parsed["recommendation_reason"] = (
        f"{parsed.get('recommendation_reason', '').strip()} Evidence-capped weighted score: "
        f"{parsed['overall_score']}/100."
    ).strip()
    parsed["raw_json"] = content
    return parsed
