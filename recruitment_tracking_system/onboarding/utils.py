import hashlib
import io
import base64
from datetime import datetime
import os
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image

from app_settings.models import GlobalAuditLog

def log_onboarding_action(user=None, candidate=None, action="", details=None, ip_address=None, user_agent=None):
    return GlobalAuditLog.objects.create(
        module="onboarding",
        action=action,
        performed_by=user,
        candidate=candidate,
        details=details or {},
        ip_address=ip_address,
        user_agent=user_agent or ""
    )

def generate_signing_certificate(signature_request, doc=None, ip_address=None, user_agent=None):
    from .models import OnboardingSigningCertificate
    candidate = signature_request.submission.invitation.candidate
    
    # Verification Hash
    signed_pdf_path = ""
    if doc and doc.signed_pdf:
        signed_pdf_path = doc.signed_pdf.name
    elif signature_request.signed_pdf:
        signed_pdf_path = signature_request.signed_pdf.name
        
    v_hash = "N/A"
    if signed_pdf_path:
        try:
            with default_storage.open(signed_pdf_path, 'rb') as f:
                v_hash = hashlib.sha256(f.read()).hexdigest()
        except Exception:
            pass

    signed_at = signature_request.signed_at or timezone.now()
    cert_ref = hashlib.sha1(f"{signature_request.id}-{candidate.candidate_id}-{signed_at.isoformat()}".encode()).hexdigest()[:16].upper()

    def _short_hash(value, head=10, tail=22):
        raw = str(value or "").strip()
        if not raw or raw == "N/A":
            return "N/A"
        if len(raw) <= head + tail + 3:
            return raw
        return f"{raw[:head]}...{raw[-tail:]}"

    # Build PDF using canvas for layout fidelity (matches reference certificate style)
    buffer = io.BytesIO()
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(buffer, pagesize=A4)
    page_w, page_h = A4

    margin = 34
    left = margin
    right = page_w - margin
    bottom = margin
    top = page_h - margin

    # Outer border
    c.setLineWidth(2)
    c.setStrokeColor(colors.black)
    c.rect(left, bottom, right - left, top - bottom, stroke=1, fill=0)

    # Header region
    header_h = 115
    header_bottom = top - header_h
    c.setLineWidth(2)
    c.line(left, header_bottom, right, header_bottom)

    # Logo (left)
    logo_path = os.path.join(str(getattr(settings, "BASE_DIR", "")), "static", "images", "ultimatix_logo.jpg")
    try:
        if os.path.exists(logo_path):
            logo = ImageReader(logo_path)
            c.drawImage(logo, left + 28, header_bottom + 18, width=160, height=72, preserveAspectRatio=True, mask="auto")
    except Exception:
        pass

    # Title + subtitle (right)
    c.setFont("Helvetica-Bold", 26)
    c.setFillColor(colors.HexColor("#1f2a44"))
    c.drawRightString(right - 18, top - 36, "Signature Certificate")
    c.setFont("Helvetica", 12)
    c.setFillColor(colors.HexColor("#4A5568"))
    c.drawRightString(right - 18, top - 58, "This certificate verifies the onboarding e-signature completion")

    # Section helpers
    def draw_section_title(y, text):
        c.setFillColor(colors.HexColor("#1f2937"))
        c.setFont("Helvetica-Bold", 16)
        c.drawString(left + 16, y, text)
        c.setStrokeColor(colors.HexColor("#CBD5E0"))
        c.setLineWidth(1)
        c.line(left + 16, y - 8, right - 16, y - 8)
        return y - 28

    def draw_kv(y, label, value):
        c.setFillColor(colors.HexColor("#4B5563"))
        c.setFont("Helvetica-Bold", 13)
        c.drawString(left + 16, y, f"{label}:")

        c.setFillColor(colors.black)
        c.setFont("Helvetica", 13)
        c.drawString(left + 210, y, str(value or "N/A"))
        return y - 24

    # Body sections
    y = header_bottom - 34
    y = draw_section_title(y, "Certificate Information")
    y = draw_kv(y, "Certificate No", f"CERT-{cert_ref}")
    y = draw_kv(y, "Document", doc.title if doc else "Onboarding Document")
    y = draw_kv(y, "Signed At", signed_at.strftime("%Y-%m-%d %H:%M:%S"))
    y = draw_kv(y, "Signed PDF SHA-256", _short_hash(v_hash, head=10, tail=28))

    y -= 10
    y = draw_section_title(y, "Candidate Information")
    y = draw_kv(y, "Candidate ID", candidate.candidate_id)
    y = draw_kv(y, "Candidate Name", candidate.full_name)
    y = draw_kv(y, "Candidate Email", candidate.email)

    # Footer
    footer_y = bottom + 26
    c.setStrokeColor(colors.HexColor("#111827"))
    c.setLineWidth(1)
    c.line(left + 12, bottom + 38, right - 12, bottom + 38)

    c.setFillColor(colors.HexColor("#64748b"))
    c.setFont("Helvetica", 12)
    c.drawString(left + 12, footer_y, "Ultimatix ATS")
    c.drawRightString(right - 12, footer_y, "System-generated certificate")

    c.showPage()
    c.save()

    pdf_content = buffer.getvalue()
    buffer.close()
    
    # Save Certificate
    safe_name = f"onboarding/certificates/CERT_{candidate.candidate_id}_{signature_request.id}.pdf"
    saved_path = default_storage.save(safe_name, ContentFile(pdf_content))
    
    cert = OnboardingSigningCertificate.objects.create(
        signature_request=signature_request,
        document=doc,
        certificate_pdf=saved_path,
        verification_hash=v_hash
    )
    
    # Log the event
    log_onboarding_action(
        candidate=candidate,
        action="CERTIFICATE_GENERATED",
        details={
            "certificate_id": cert.id,
            "document_id": doc.id if doc else None,
            "verification_hash": v_hash,
            "certificate_ref": cert_ref,
        },
        ip_address=ip_address,
        user_agent=user_agent
    )
    
    return cert


def regenerate_signing_certificate_pdf(cert, ip_address=None, user_agent=None):
    signature_request = cert.signature_request
    candidate = signature_request.submission.invitation.candidate
    doc = cert.document

    # Verification Hash
    signed_pdf_path = ""
    if doc and getattr(doc, "signed_pdf", None):
        signed_pdf_path = doc.signed_pdf.name
    elif getattr(signature_request, "signed_pdf", None):
        signed_pdf_path = signature_request.signed_pdf.name

    v_hash = "N/A"
    if signed_pdf_path:
        try:
            with default_storage.open(signed_pdf_path, "rb") as f:
                v_hash = hashlib.sha256(f.read()).hexdigest()
        except Exception:
            pass

    signed_at = signature_request.signed_at or timezone.now()
    cert_ref = hashlib.sha1(f"{signature_request.id}-{candidate.candidate_id}-{signed_at.isoformat()}".encode()).hexdigest()[:16].upper()

    def _short_hash(value, head=10, tail=22):
        raw = str(value or "").strip()
        if not raw or raw == "N/A":
            return "N/A"
        if len(raw) <= head + tail + 3:
            return raw
        return f"{raw[:head]}...{raw[-tail:]}"

    # Build PDF
    buffer = io.BytesIO()
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(buffer, pagesize=A4)
    page_w, page_h = A4

    margin = 34
    left = margin
    right = page_w - margin
    bottom = margin
    top = page_h - margin

    c.setLineWidth(2)
    c.setStrokeColor(colors.black)
    c.rect(left, bottom, right - left, top - bottom, stroke=1, fill=0)

    header_h = 115
    header_bottom = top - header_h
    c.setLineWidth(2)
    c.line(left, header_bottom, right, header_bottom)

    logo_path = os.path.join(str(getattr(settings, "BASE_DIR", "")), "static", "images", "ultimatix_logo.jpg")
    try:
        if os.path.exists(logo_path):
            logo = ImageReader(logo_path)
            c.drawImage(logo, left + 28, header_bottom + 18, width=160, height=72, preserveAspectRatio=True, mask="auto")
    except Exception:
        pass

    c.setFont("Helvetica-Bold", 26)
    c.setFillColor(colors.HexColor("#1f2a44"))
    c.drawRightString(right - 18, top - 36, "Signature Certificate")
    c.setFont("Helvetica", 12)
    c.setFillColor(colors.HexColor("#4A5568"))
    c.drawRightString(right - 18, top - 58, "This certificate verifies the onboarding e-signature completion")

    def draw_section_title(y, text):
        c.setFillColor(colors.HexColor("#1f2937"))
        c.setFont("Helvetica-Bold", 16)
        c.drawString(left + 16, y, text)
        c.setStrokeColor(colors.HexColor("#CBD5E0"))
        c.setLineWidth(1)
        c.line(left + 16, y - 8, right - 16, y - 8)
        return y - 28

    def draw_kv(y, label, value):
        c.setFillColor(colors.HexColor("#4B5563"))
        c.setFont("Helvetica-Bold", 13)
        c.drawString(left + 16, y, f"{label}:")

        c.setFillColor(colors.black)
        c.setFont("Helvetica", 13)
        c.drawString(left + 210, y, str(value or "N/A"))
        return y - 24

    y = header_bottom - 34
    y = draw_section_title(y, "Certificate Information")
    y = draw_kv(y, "Certificate No", f"CERT-{cert_ref}")
    y = draw_kv(y, "Document", doc.title if doc else "Onboarding Document")
    y = draw_kv(y, "Signed At", signed_at.strftime("%Y-%m-%d %H:%M:%S"))
    y = draw_kv(y, "Signed PDF SHA-256", _short_hash(v_hash, head=10, tail=28))

    y -= 10
    y = draw_section_title(y, "Candidate Information")
    y = draw_kv(y, "Candidate ID", candidate.candidate_id)
    y = draw_kv(y, "Candidate Name", candidate.full_name)
    y = draw_kv(y, "Candidate Email", candidate.email)

    footer_y = bottom + 26
    c.setStrokeColor(colors.HexColor("#111827"))
    c.setLineWidth(1)
    c.line(left + 12, bottom + 38, right - 12, bottom + 38)

    c.setFillColor(colors.HexColor("#64748b"))
    c.setFont("Helvetica", 12)
    c.drawString(left + 12, footer_y, "Ultimatix ATS")
    c.drawRightString(right - 12, footer_y, "System-generated certificate")

    c.showPage()
    c.save()

    pdf_content = buffer.getvalue()
    buffer.close()

    filename = os.path.basename(cert.certificate_pdf.name) if cert.certificate_pdf and cert.certificate_pdf.name else f"CERT_{candidate.candidate_id}_{signature_request.id}.pdf"
    cert.certificate_pdf.save(filename, ContentFile(pdf_content), save=False)
    cert.verification_hash = v_hash
    cert.save(update_fields=["certificate_pdf", "verification_hash"])

    log_onboarding_action(
        candidate=candidate,
        action="CERTIFICATE_REGENERATED",
        details={"certificate_id": cert.id, "document_id": doc.id if doc else None, "verification_hash": v_hash, "certificate_ref": cert_ref},
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return cert
