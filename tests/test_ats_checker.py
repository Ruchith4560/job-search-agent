"""Tests for the ATS scoring engine and optimization pass."""

from agent.jobs.schema import Job
from agent.profile.schema import (
    EducationItem,
    MasterProfile,
    PersonalInfo,
    ProjectItem,
    SkillItem,
)
from agent.resume.ats_checker import ATSChecker, ATSScoreResult
from agent.resume.schema import ResumeData, ResumeEducation, ResumeExperience, ResumeProject


def build_sample_resume() -> ResumeData:
    return ResumeData(
        name="Ruchith Macha",
        headline="Software Engineer Intern | MERN Stack & Python Developer",
        email="macharuchith1@gmail.com",
        phone="6305239230",
        location="Hyderabad, Telangana, India",
        github_url="https://github.com/Ruchith4560",
        summary="Computer Science undergraduate at Anurag University with hands-on experience building full-stack web applications using React, Node.js, and MongoDB.",
        skills_by_category={
            "Languages": ["JavaScript", "Python", "C++", "Java", "SQL"],
            "Frameworks": ["React", "Node.js", "Express.js", "FastAPI"],
            "Databases & Cloud": ["MongoDB", "Docker", "Git", "GitHub"],
        },
        education=[
            ResumeEducation(
                school="Anurag University",
                degree="B.Tech in Computer Science and Engineering",
                dates="Expected 2028",
                notes="CGPA: 8.5 / 10.0",
            )
        ],
        experience=[],
        projects=[
            ResumeProject(
                name="Servicedesk Pro",
                stack=["React", "Node.js", "MongoDB", "Express"],
                bullets=[
                    "Built responsive incident tracking dashboard using React and Tailwind CSS.",
                    "Implemented RESTful backend APIs with Node.js and Express.",
                ],
            ),
            ResumeProject(
                name="Travel Expense Calculator",
                stack=["Python", "Docker", "MongoDB"],
                bullets=[
                    "Engineered multi-currency expense tracker containerized with Docker.",
                    "Managed database queries with optimized indexing in MongoDB.",
                ],
            ),
        ],
        certifications=[],
    )


def build_sample_profile() -> MasterProfile:
    return MasterProfile(
        personal_info=PersonalInfo(
            name="Ruchith Macha",
            headline="Software Engineer",
            email="macharuchith1@gmail.com",
            location="Hyderabad",
        ),
        skills=[
            SkillItem(name="React", category="Frontend", source="github"),
            SkillItem(name="Node.js", category="Backend", source="github"),
            SkillItem(name="Python", category="Languages", source="github"),
            SkillItem(name="Docker", category="DevOps", source="github"),
            SkillItem(name="MongoDB", category="Databases", source="linkedin"),
            SkillItem(name="SQL", category="Databases", source="linkedin"),
        ],
        projects=[
            ProjectItem(name="Servicedesk Pro", description="Incident management system", source="github"),
            ProjectItem(name="Travel Expense Calculator", description="Dockerized app", source="github"),
        ],
        education=[
            EducationItem(school="Anurag University", degree="B.Tech CSE", source="linkedin", year="2024 - 2028")
        ],
    )


def test_ats_checker_format_compliance() -> None:
    checker = ATSChecker(min_ats_score=85.0)
    resume = build_sample_resume()
    format_score = checker.verify_format_compliance(resume)
    assert format_score == 100.0


def test_ats_checker_scoring() -> None:
    checker = ATSChecker(min_ats_score=85.0)
    resume = build_sample_resume()
    job = Job.create(
        title="Software Engineer Intern",
        company="Canonical",
        url="https://canonical.com/careers/1",
        source="greenhouse",
        description="Looking for an intern with knowledge of React, Node.js, Python, and Docker.",
        tags=["React", "Python", "Docker"],
    )
    result = checker.score(resume, job)
    assert isinstance(result, ATSScoreResult)
    assert result.overall_score >= 85.0
    assert result.is_ats_compliant is True
    assert "React" in result.matched_keywords or "react" in [k.lower() for k in result.matched_keywords]


def test_ats_checker_optimization_enforces_threshold() -> None:
    checker = ATSChecker(min_ats_score=85.0)
    resume = build_sample_resume()
    profile = build_sample_profile()
    job = Job.create(
        title="Backend Software Engineer Intern",
        company="TechCorp",
        url="https://techcorp.com/careers/2",
        source="remotive",
        description="Seeking an engineering intern with experience in Python, SQL, Docker, and REST APIs.",
        tags=["Python", "SQL", "Docker"],
    )

    optimized_resume, result = checker.optimize_and_verify(resume, job, profile)
    assert result.overall_score >= 85.0
    assert result.is_ats_compliant is True
