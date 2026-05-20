import logging
import re

logger = logging.getLogger(__name__)

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    SKLEARN_AVAILABLE = True
except Exception:
    TfidfVectorizer = None
    cosine_similarity = None
    SKLEARN_AVAILABLE = False

try:
    import dateparser
except Exception:
    dateparser = None


SKILL_KEYWORDS = [
    "Python",
    "Java",
    "C++",
    "TensorFlow",
    "PyTorch",
    "GraphQL",
    "Scikit-learn",
    "Machine Learning",
    "Deep Learning",
    "Data Science",
    "Big Data",
    "Cloud Computing",
    "Azure",
    "MySQL",
    "MATLAB",
    "Hadoop",
    "Big-Data",
    "Data Analytics",
    "Data Analyst",
    "Predictive Modeling",
    "Keras",
    "Statistical Modeling",
    "Statistical Analysis",
    "Django",
    "Flask",
    "JavaScript",
    "TypeScript",
    "React",
    "Node.js",
    "Angular",
    "Vue.js",
    "Ruby",
    "C#",
    "Swift",
    "Scala",
    "Kotlin",
    "Rust",
    "Golang",
    "Insomnia",
    "Postman",
    "Shell Scripting",
    "Bash",
    "Spark",
    "Kafka",
    "MongoDB",
    "PostgreSQL",
    "Redis",
    "NoSQL",
    "Docker",
    "Kubernetes",
    "CI/CD",
    "GitHub",
    "GitLab",
    "Jenkins",
    "Terraform",
    "Ansible",
    "Puppet",
    "Selenium",
    "Network Security",
    "DevOps",
    "Agile",
    "Scrum",
    "Test Automation",
    "Unit Testing",
    "Pandas",
    "NumPy",
    "Matplotlib",
    "Seaborn",
    "OpenCV",
    "Computer Vision",
    "Reinforcement Learning",
    "Data Engineering",
    "Data Warehousing",
    "Tableau",
    "Power BI",
    "Business Intelligence",
    "Data Pipeline",
    "Graph Databases",
    "Elasticsearch",
    "Quantum Computing",
    "JIRA",
    "Blockchain",
    "Cryptocurrency",
    "Smart Contracts",
    "Microservice",
    "API Development",
    "OAuth",
    "Web Services",
    "RESTful APIs",
    "Web Scraping",
    "Web Development",
    "Mobile Development",
    "Android",
    "Flutter",
    "Xamarin",
    "Networking",
    "Cybersecurity",
    "Large Language Model",
    "Penetration Testing",
    "Intrusion Detection",
    "Cloud Security",
    "DevSecOps",
    "Alteryx",
    "Data Mining",
    "Data Visualization",
    "Data Visualisation",
    "Microsoft Office",
    "Powerpoint",
    ".NET",
    "Dotnet",
    "MXNet",
    "Apache",
    "Feature Engineering",
    "Data Exploration",
    "Prescriptive Analytics",
    "Predictive Analytics",
    "Predictive Models Analysis",
    "Forecast",
    "Quantitative analysis",
    "Assembly",
    "Perl",
    "Qlik Sense",
    "Snowflake",
    "Neural Network",
    "GANs",
    "LangChain",
    "MLflow",
    "Hugging Face",
    "AutoML",
    "XGBoost",
    "LightGBM",
    "CatBoost",
    "Grafana",
    "Burp Suite",
    "Kali Linux",
    "Nmap",
    "Wireshark",
    "Packet Tracer",
    "Splunk",
    "Metasploit",
    "Prometheus",
    "TestNG",
    "JUnit",
    "Cypress",
    "React Native",
    "SwiftUI",
    "Ionic",
]

SINGLE_DIGIT_SKILLS = [
    "AI",
    "R",
    "C",
    "AWS",
    "LLM",
    "GO",
    "NLP",
    "ETL",
    "GCP",
    "HTML",
    "CSS",
    "PHP",
    "SQL",
    "ELK",
    "JWT",
    "SPSS",
    "SOAP",
    "JAX",
    "IAM",
    "Go",
    "Aws",
    "Visio",
    "Excel",
    "Vuex",
]


def normalize_skill(skill):
    return str(skill).replace("-", "").replace(" ", "").lower()


def extract_skills(text):
    text_lower = (text or "").lower()
    normalized_skill_map = {normalize_skill(skill): skill for skill in SKILL_KEYWORDS}
    extracted_skills = [
        normalized_skill_map[norm_skill]
        for norm_skill in normalized_skill_map
        if norm_skill in normalize_skill(text_lower)
    ]
    return extracted_skills if extracted_skills else ["No Skills Found"]


def deduplicate_skills(skills):
    seen = {}
    for skill in skills or []:
        key = str(skill).lower()
        if key not in seen or str(skill)[:1].isupper():
            seen[key] = skill
    return list(seen.values())


def match_single_digit_skills(text, singledigit_skills=None):
    singledigit_skills = singledigit_skills or SINGLE_DIGIT_SKILLS
    pattern = r"\b(" + "|".join(map(re.escape, singledigit_skills)) + r")\b"
    matches = re.findall(pattern, text or "", flags=re.IGNORECASE)
    return sorted(set(matches))


def extract_skills_from_job(job_description):
    job_description_lower = (job_description or "").lower()
    normalized_skill_map = {normalize_skill(skill): skill for skill in SKILL_KEYWORDS}
    job_skills = [
        normalized_skill_map[norm_skill]
        for norm_skill in normalized_skill_map
        if norm_skill in normalize_skill(job_description_lower)
    ]
    return job_skills if job_skills else ["No Skills Found"]


def match_resume_skills(resume_skills, job_skills):
    resume_skills_map = {normalize_skill(skill): skill for skill in (resume_skills or [])}
    job_skills_map = {normalize_skill(skill): skill for skill in (job_skills or [])}
    matched_skills_lower = set(resume_skills_map.keys()) & set(job_skills_map.keys())
    matched_skills = [resume_skills_map[skill] for skill in matched_skills_lower]
    missing_skills = [job_skills_map[skill] for skill in set(job_skills_map.keys()) - set(resume_skills_map.keys())]
    return matched_skills, missing_skills


def _tokenize(text):
    return re.findall(r"[a-z0-9+#.]+", (text or "").lower())


def _jaccard_similarity(a_tokens, b_tokens):
    a_set = set(a_tokens)
    b_set = set(b_tokens)
    if not a_set or not b_set:
        return 0.0
    return len(a_set & b_set) / float(len(a_set | b_set))


def match_resume_to_job(resume_text, job_description):
    if not resume_text or not job_description:
        return 0.0
    if SKLEARN_AVAILABLE:
        try:
            vectorizer = TfidfVectorizer()
            vectors = vectorizer.fit_transform([resume_text, job_description])
            return round(float(cosine_similarity(vectors)[0, 1]) * 100, 2)
        except Exception as exc:
            logger.warning("TF-IDF match failed, falling back to Jaccard: %s", exc)
    score = _jaccard_similarity(_tokenize(resume_text), _tokenize(job_description)) * 100.0
    return round(score, 2)


def _month_index(name):
    month_map = {
        "jan": 1,
        "january": 1,
        "feb": 2,
        "february": 2,
        "mar": 3,
        "march": 3,
        "apr": 4,
        "april": 4,
        "may": 5,
        "jun": 6,
        "june": 6,
        "jul": 7,
        "july": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "sept": 9,
        "september": 9,
        "oct": 10,
        "october": 10,
        "nov": 11,
        "november": 11,
        "dec": 12,
        "december": 12,
    }
    return month_map.get((name or "").lower().strip(), 0)


def _years_from_date_ranges(text):
    normalized = (text or "").replace("\u2013", "-").replace("\u2014", "-")
    pattern = r"([A-Za-z]{3,9})\s+(\d{4})\s*(?:-|to)\s*([A-Za-z]{3,9})\s+(\d{4})"
    matches = re.findall(pattern, normalized)
    total = 0.0
    for start_month, start_year, end_month, end_year in matches:
        try:
            sm = _month_index(start_month)
            em = _month_index(end_month)
            if not sm or not em:
                continue
            start_year = int(start_year)
            end_year = int(end_year)
            months = (end_year - start_year) * 12 + (em - sm)
            total += max(0.0, months / 12.0)
        except Exception:
            continue
    return total


def categorize_experience(text):
    resume_years = 0.0
    match = re.search(r"(?:(?:over|more than|at least|up to)\s*)?(\d{1,2})\s*(?:\+\s*)?years?", (text or "").lower())
    if match:
        resume_years = float(match.group(1))
    else:
        resume_years = _years_from_date_ranges(text)
        if not resume_years and dateparser is not None:
            date_match = re.findall(
                r"([A-Za-z]{3,9})\s+(\d{4})\s*(?:-|to)\s*([A-Za-z]{3,9})\s+(\d{4})",
                text or "",
            )
            for start_month, start_year, end_month, end_year in date_match:
                try:
                    start_date = dateparser.parse(f"{start_month} {start_year}")
                    end_date = dateparser.parse(f"{end_month} {end_year}")
                    if start_date and end_date:
                        duration = (end_date.year - start_date.year) + (end_date.month - start_date.month) / 12.0
                        resume_years += max(0.0, duration)
                except Exception:
                    continue

    if resume_years >= 7:
        level = "Senior"
    elif resume_years >= 3:
        level = "Mid-Level"
    elif resume_years > 0:
        level = "Junior"
    else:
        level = "Not Mentioned"
    return level, round(resume_years, 2)


def get_required_experience(job_description):
    text = (job_description or "").lower()
    if "intern" in text or "pursuing" in text:
        return "Intern"
    if any(term in text for term in ["entry-level", "0-2 years", "junior"]):
        return "Junior"
    if any(term in text for term in ["3-7 years", "mid-level"]):
        return "Mid-Level"
    if any(term in text for term in ["7+ years", "senior"]):
        return "Senior"
    return "Not Mentioned"


def adjust_match_score(match_score, experience_level, job_description, resume_skills):
    job_skills = extract_skills_from_job(job_description)
    single_skills = match_single_digit_skills(job_description, SINGLE_DIGIT_SKILLS)
    job_skills = job_skills + single_skills

    job_description_lower = (job_description or "").lower()
    score = float(match_score or 0)

    if any(term in job_description_lower for term in ["intern", "internship", "interns", "entry-level"]):
        if experience_level in ["Intern", "Junior", "Mid-Level", "Senior"]:
            score = min(100.0, score * 1.20)
    elif any(term in job_description_lower for term in ["entry-level", "entry level", "0-2 year"]):
        if experience_level in ["Junior", "Senior", "Mid-Level"]:
            score = min(100.0, score * 1.20)
    elif any(term in job_description_lower for term in ["mid-level", "mid level", "3-7 year"]):
        if experience_level in ["Senior", "Mid-Level"]:
            score = min(100.0, score * 1.20)
    elif any(term in job_description_lower for term in ["senior", "7+ year"]):
        if experience_level in ["Senior", "senior"]:
            score = min(100.0, score * 1.20)

    skill_overlap = len(set(resume_skills or []) & set(job_skills))
    if skill_overlap > 0:
        score = min(100.0, score * (1 + (0.02 * skill_overlap)))

    return min(100.0, round(score, 2)), skill_overlap


def _education_rank(text):
    text = (text or "").lower()
    ranking_rules = [
        (4, ("phd", "doctor", "doctorate")),
        (3, ("master", "m.tech", "mtech", "m.sc", "msc", "mba", "mca", "m.e", "me ")),
        (2, ("bachelor", "b.tech", "btech", "b.sc", "bsc", "bca", "b.e", "be ")),
        (1, ("diploma", "polytechnic", "iti")),
        (0, ("12th", "xii", "hsc", "higher secondary", "10th", "ssc", "secondary")),
    ]
    for rank, keywords in ranking_rules:
        if any(keyword in text for keyword in keywords):
            return rank
    return -1


def _education_label(rank):
    labels = {
        4: "PhD",
        3: "Masters",
        2: "Bachelors",
        1: "Diploma",
        0: "School",
    }
    return labels.get(rank, "Not Mentioned")


def get_required_education(job_description):
    return _education_label(_education_rank(job_description))


def _experience_rank(level):
    levels = {"Intern": 0, "Junior": 1, "Mid-Level": 2, "Senior": 3}
    return levels.get(level or "", -1)


def score_resume_against_job(resume_text, job_description, candidate_education=""):
    if not resume_text or not job_description:
        return None
    resume_skills = extract_skills(resume_text)
    resume_skills += match_single_digit_skills(resume_text, SINGLE_DIGIT_SKILLS)
    resume_skills = deduplicate_skills(resume_skills)
    job_skills = extract_skills_from_job(job_description)
    job_skills += match_single_digit_skills(job_description, SINGLE_DIGIT_SKILLS)
    job_skills = deduplicate_skills(job_skills)
    matched_skills, missing_skills = match_resume_skills(resume_skills, job_skills)

    experience_level, experience_years = categorize_experience(resume_text)
    required_experience = get_required_experience(job_description)
    candidate_rank = _experience_rank(experience_level)
    required_rank = _experience_rank(required_experience)

    if required_experience == "Not Mentioned":
        experience_score = 100.0
    else:
        diff = candidate_rank - required_rank
        if diff >= 0:
            experience_score = 100.0
        elif diff == -1:
            experience_score = 50.0
        else:
            experience_score = 0.0

    required_education = get_required_education(job_description)
    candidate_education_rank = _education_rank(candidate_education or resume_text)
    required_education_rank = _education_rank(job_description)
    if required_education == "Not Mentioned":
        education_score = 100.0
    else:
        diff = candidate_education_rank - required_education_rank
        if diff >= 0:
            education_score = 100.0
        elif diff == -1:
            education_score = 50.0
        else:
            education_score = 0.0

    if job_skills and "No Skills Found" not in job_skills:
        skills_score = (len(matched_skills) / max(1, len(job_skills))) * 100.0
    else:
        skills_score = 50.0

    overall_score = (0.5 * skills_score) + (0.3 * experience_score) + (0.2 * education_score)
    text_similarity = match_resume_to_job(resume_text, job_description)

    if overall_score >= 80 and skills_score >= 70 and experience_score >= 70:
        status = "Full Match"
    elif overall_score >= 50:
        status = "Partial Match"
    elif overall_score > 0:
        if skills_score < 50 or experience_score < 50 or education_score < 50:
            status = "Below Criteria"
        else:
            status = "Low Match"
    else:
        status = "No Match"

    skill_overlap = len(matched_skills)
    return {
        "match_score": round(overall_score, 2),
        "experience_level": experience_level,
        "experience_years": experience_years,
        "skills_matched": skill_overlap,
        "skills": resume_skills,
        "skills_required": len(job_skills) if job_skills and "No Skills Found" not in job_skills else 0,
        "skills_matched_list": matched_skills,
        "skills_missing_list": missing_skills,
        "skills_score": round(skills_score, 2),
        "experience_score": round(experience_score, 2),
        "education_score": round(education_score, 2),
        "text_similarity": text_similarity,
        "education_required": required_education,
        "education_candidate": _education_label(candidate_education_rank),
        "match_status": status,
    }
