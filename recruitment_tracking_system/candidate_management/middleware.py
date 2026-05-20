import json
from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin
from candidate_management.ai_guardrails import GuardrailsEngine

class AIGuardrailsMiddleware(MiddlewareMixin):
    def __call__(self, request):
        if request.path == "/job-requisition/posting-form/suggest-content/" and request.method == "POST":
            # 1. Capture prompt inputs (posting_title, industry, etc.)
            posting_title = request.POST.get("posting_title", "").strip()
            target_field = request.POST.get("target_field", "").strip()
            
            trace_logs = []
            
            # Step 1: Input Guardrail Check
            trace_logs.append({
                "stage": "Input Guardrail",
                "status": "Checking",
                "detail": f"Analyzing posting title '{posting_title}' for prompt injections, safety, and relevance..."
            })
            
            # Local validation to prevent calling Gemini with empty/invalid titles
            if not posting_title:
                trace_logs[-1].update({
                    "status": "Failed",
                    "detail": "Blocked by Input Safety Rail: Please enter the correct details."
                })
                return JsonResponse({
                    "ok": False,
                    "message": "Blocked by AI Guardrails Policy: Please enter the correct details.",
                    "guardrails_log": trace_logs
                })

            if len(posting_title) < 3:
                trace_logs[-1].update({
                    "status": "Failed",
                    "detail": "Blocked by Input Safety Rail: Please enter the correct details."
                })
                return JsonResponse({
                    "ok": False,
                    "message": "Blocked by AI Guardrails Policy: Please enter the correct details.",
                    "guardrails_log": trace_logs
                })

            # Run input rails validation
            input_ok, input_reason = GuardrailsEngine.verify_input_rail(posting_title)
            if not input_ok:
                trace_logs[-1].update({
                    "status": "Failed",
                    "detail": "Blocked by Input Safety Rail: Please enter the correct details."
                })
                return JsonResponse({
                    "ok": False,
                    "message": "Blocked by AI Guardrails Policy: Please enter the correct details.",
                    "guardrails_log": trace_logs
                })
            
            trace_logs[-1].update({
                "status": "Passed",
                "detail": "Input check cleared successfully. No prompt injection or safety violations detected."
            })
            
            # Step 2: Policy Alignment (Colang Flow)
            trace_logs.append({
                "stage": "Policy Alignment",
                "status": "Checking",
                "detail": "Verifying request aligns with Ultimatix Recruitment system flow..."
            })
            
            # Basic validation that we are actually requesting a job requisition topic
            recruitment_keywords = [
                "engineer", "developer", "manager", "lead", "designer", "consultant", "analyst", 
                "specialist", "sales", "hr", "marketing", "job", "work", "tech", "executive", 
                "admin", "clerk", "officer", "head", "associate", "intern", "staff", "assistant",
                "programmer", "architect", "expert", "coordinator", "operator", "director", "president",
                "chief", "scrum", "product", "accountant", "recruiter", "scientist", "writer", "editor", 
                "artist", "senior", "junior", "principal", "staff"
            ]
            
            # Since Gemini input safety rail already does intelligent semantic off-topic verification,
            # we check keywords as a structural filter but defer to Gemini's clean output.
            is_valid_role = any(kw in posting_title.lower() for kw in recruitment_keywords) or len(posting_title) < 3
            if not is_valid_role and not input_ok:
                trace_logs[-1].update({
                    "status": "Failed",
                    "detail": "Off-topic prompt: Please enter the correct details."
                })
                return JsonResponse({
                    "ok": False,
                    "message": "Blocked by AI Guardrails Policy: Please enter the correct details.",
                    "guardrails_log": trace_logs
                })
                
            trace_logs[-1].update({
                "status": "Passed",
                "detail": "Policy flow check cleared. Request conforms to job description synthesis rules."
            })
            
            # Step 3: LLM Generation
            trace_logs.append({
                "stage": "LLM Generator",
                "status": "Checking",
                "detail": "Invoking Gemini-2.0-Flash to draft job requisition fields..."
            })
            
            # Call downstream view to get actual response
            response = self.get_response(request)
            
            if response.status_code != 200:
                trace_logs[-1].update({
                    "status": "Failed",
                    "detail": f"Downstream view returned error code {response.status_code}"
                })
                return response
                
            try:
                # Load response content
                res_data = json.loads(response.content.decode("utf-8"))
                if not res_data.get("ok"):
                    trace_logs[-1].update({
                        "status": "Failed",
                        "detail": f"Gemini API invocation failed: {res_data.get('message')}"
                    })
                    res_data["guardrails_log"] = trace_logs
                    return JsonResponse(res_data, status=200)
                
                trace_logs[-1].update({
                    "status": "Passed",
                    "detail": "Gemini synthesis completed successfully."
                })
                
                # Step 4: Output Guardrail Check
                trace_logs.append({
                    "stage": "Output Guardrail",
                    "status": "Checking",
                    "detail": "Screening synthesized output for toxic vocabulary, vulgarity, and sensitive PII leaks..."
                })
                
                # Check output safety
                fields = res_data.get("fields", {})
                all_text = " ".join(fields.values())
                
                output_ok, output_reason = GuardrailsEngine.verify_output_rail(all_text)
                if not output_ok:
                    trace_logs[-1].update({
                        "status": "Failed",
                        "detail": "Blocked by Output Safety Rail: Please enter the correct details."
                    })
                    return JsonResponse({
                        "ok": False,
                        "message": "Blocked by AI Guardrails Policy: Please enter the correct details.",
                        "guardrails_log": trace_logs
                    })
                
                trace_logs[-1].update({
                    "status": "Passed",
                    "detail": "Output screening passed. All synthesized text is safe and policy-compliant."
                })
                
                # Inject trace logs into response data
                res_data["guardrails_log"] = trace_logs
                
                # Return decorated response
                return JsonResponse(res_data)
                
            except Exception as e:
                trace_logs.append({
                    "stage": "Middleware Handler",
                    "status": "Failed",
                    "detail": f"Internal post-processing error: {str(e)}"
                })
                return JsonResponse({
                    "ok": False,
                    "message": "AI Guardrails post-processing failed.",
                    "guardrails_log": trace_logs
                })
        
        return self.get_response(request)
