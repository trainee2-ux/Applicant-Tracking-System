from django.db import models
from django.db import transaction
from job_requisition.models import JobRequisition


class Candidate(models.Model):
    GENDER_CHOICES = [
        ("Male", "Male"),
        ("Female", "Female"),
        ("Other", "Other"),
    ]

    candidate_id = models.CharField(max_length=30, unique=True, blank=True)
    candidate_code = models.CharField(max_length=20, default='')
    full_name = models.CharField(max_length=150)
    email = models.EmailField(unique=True)
    contact_number = models.CharField(max_length=20)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=20, choices=GENDER_CHOICES, blank=True)
    current_city = models.CharField(max_length=120, blank=True)
    country = models.CharField(max_length=120, blank=True)
    state = models.CharField(max_length=120, blank=True)
    pan = models.CharField(max_length=20, blank=True)
    aadhaar = models.CharField(max_length=25, blank=True)
    pf = models.CharField(max_length=40, blank=True, default='')
    esic = models.CharField(max_length=40, blank=True, default='')
    social_media_link = models.URLField(blank=True)
    address = models.TextField(blank=True)
    resume_path = models.CharField(max_length=255, blank=True)
    profile_photo_path = models.CharField(max_length=255, blank=True)
    highest_education_level = models.CharField(max_length=255, blank=True)
    degree_name = models.CharField(max_length=1000, blank=True)
    institute_name = models.CharField(max_length=1000, blank=True)
    year_of_passing = models.CharField(max_length=50, blank=True)
    percentage_cgpa = models.CharField(max_length=255, blank=True)
    certifications = models.TextField(blank=True)
    skills = models.TextField(blank=True)
    experience = models.CharField(max_length=80, blank=True)
    employment_history = models.TextField(blank=True)
    references = models.TextField(blank=True)
    custom_tags = models.TextField(blank=True)
    applied_position = models.CharField(max_length=180, blank=True)
    status = models.CharField(max_length=40, default="Applied")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.candidate_id} - {self.full_name}"

    def save(self, *args, **kwargs):
        if not self.candidate_id:
            with transaction.atomic():
                latest = Candidate.objects.select_for_update().order_by("-id").first()
                next_num = (latest.id + 1) if latest else 1
                while True:
                    generated = f"CAND{next_num:04d}"
                    if not Candidate.objects.filter(candidate_id=generated).exists():
                        self.candidate_id = generated
                        break
                    next_num += 1

        if not self.candidate_code:
            self.candidate_code = self.candidate_id

        super().save(*args, **kwargs)


class CandidateEducation(models.Model):
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="education_records")
    sequence = models.PositiveIntegerField(default=0)
    level = models.CharField(max_length=60)
    course = models.CharField(max_length=180, blank=True)
    institute = models.CharField(max_length=255, blank=True)
    board_university = models.CharField(max_length=255, blank=True)
    year_of_passing = models.CharField(max_length=20, blank=True)
    score = models.CharField(max_length=60, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sequence", "id"]

    def __str__(self):
        return f"{self.candidate.candidate_id} - {self.level}"


class CandidateNote(models.Model):
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="notes")
    activity = models.ForeignKey("CandidateActivity", on_delete=models.SET_NULL, null=True, blank=True, related_name="notes")
    note = models.TextField()
    created_by = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.candidate.candidate_id} - {self.created_by or 'Recruiter'}"


class CandidateActivity(models.Model):
    ACTIVITY_TYPE_CHOICES = [
        ("call", "Call"),
        ("email", "Email"),
        ("meeting", "Meeting"),
        ("todo", "Todo"),
        ("document", "Document"),
    ]
    STATUS_CHOICES = [
        ("Scheduled", "Scheduled"),
        ("Done", "Done"),
        ("Cancelled", "Cancelled"),
    ]

    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="activities")
    activity_type = models.CharField(max_length=20, choices=ACTIVITY_TYPE_CHOICES)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Scheduled")
    created_by = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    document = models.FileField(upload_to="candidate_activities/", null=True, blank=True)

    class Meta:
        ordering = ["scheduled_at", "-created_at"]

    def __str__(self):
        return f"{self.candidate.candidate_id} - {self.activity_type} - {self.title}"


class CandidateEvaluation(models.Model):
    STATUS_CHOICES = [
        ("Hired", "Hired"),
        ("On-Hold", "On-Hold"),
        ("Strong Hire", "Strong Hire"),
        ("Shortlist", "Shortlist"),
        ("Wait-List", "Wait-List"),
        ("Move to Next Round", "Move to Next Round"),
    ]

    candidate = models.ForeignKey(
        Candidate,
        on_delete=models.CASCADE,
        related_name="evaluations",
        null=True,
        blank=True,
    )
    candidate_code = models.CharField(max_length=30)
    candidate_name = models.CharField(max_length=150)
    candidate_phone = models.CharField(max_length=20)
    candidate_email = models.EmailField()
    posting_title = models.CharField(max_length=180)
    interviewed_by = models.CharField(max_length=150)
    interview_round = models.CharField(max_length=80, blank=True)
    technical_score = models.DecimalField(max_digits=5, decimal_places=2)
    communication_score = models.DecimalField(max_digits=5, decimal_places=2)
    cultural_fit_score = models.DecimalField(max_digits=5, decimal_places=2)
    overall_rating = models.DecimalField(max_digits=5, decimal_places=2)
    interviewer_comments = models.TextField(blank=True)
    assessment_form_name = models.CharField(max_length=120, blank=True)
    assessment_form_data = models.TextField(blank=True)
    feedback_form_name = models.CharField(max_length=120, blank=True)
    feedback_form_data = models.TextField(blank=True)
    status = models.CharField(max_length=40, choices=STATUS_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.candidate_code} - {self.candidate_name}"


class ResumeVersion(models.Model):
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="resume_versions")
    version = models.PositiveIntegerField()
    file_path = models.CharField(max_length=255)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version", "-uploaded_at"]
        unique_together = [("candidate", "version")]

    def __str__(self):
        return f"{self.candidate.candidate_id} - v{self.version}"


class ProfilePhotoVersion(models.Model):
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="profile_photo_versions")
    version = models.PositiveIntegerField()
    file_path = models.CharField(max_length=255)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version", "-uploaded_at"]
        unique_together = [("candidate", "version")]

    def __str__(self):
        return f"{self.candidate.candidate_id} - photo v{self.version}"


class CandidateJobApplication(models.Model):
    stage = models.CharField(max_length=40, default="Applied")
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="job_applications")
    job = models.ForeignKey(JobRequisition, on_delete=models.CASCADE, related_name="candidate_applications")
    resume_match_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    resume_experience_level = models.CharField(max_length=30, blank=True)
    resume_experience_years = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    resume_skills_matched = models.PositiveIntegerField(default=0)
    resume_skills_required = models.PositiveIntegerField(default=0)
    resume_skill_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    resume_experience_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    resume_education_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    resume_text_similarity = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    resume_match_status = models.CharField(max_length=30, blank=True)
    resume_skills_matched_list = models.TextField(blank=True)
    resume_skills_missing_list = models.TextField(blank=True)
    resume_education_required = models.CharField(max_length=60, blank=True)
    resume_education_candidate = models.CharField(max_length=60, blank=True)
    applied_on = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-applied_on"]
        unique_together = [("candidate", "job")]

    def __str__(self):
        return f"{self.candidate.candidate_id} -> {self.job.job_id}"
