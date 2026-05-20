from django.contrib import admin
from .models import (
    AssessmentField,
    AssessmentForm,
    City,
    CompanyInfo,
    Country,
    EducationLevel,
    PortalRoleAccess,
    RoleMaster,
    RolePermissionSetup,
    State,
    UserMaster,
    UserMasterAudit,
)

admin.site.register(AssessmentField)
admin.site.register(AssessmentForm)
admin.site.register(City)
admin.site.register(CompanyInfo)
admin.site.register(Country)
admin.site.register(EducationLevel)
admin.site.register(PortalRoleAccess)
admin.site.register(RoleMaster)
admin.site.register(RolePermissionSetup)
admin.site.register(State)
admin.site.register(UserMaster)
admin.site.register(UserMasterAudit)
