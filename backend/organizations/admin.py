from django.contrib import admin

from .models import AuditLog, Building, Department, Employee, Floor, Gate, Organization


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "city", "country", "timezone", "created_at")
    prepopulated_fields = {"slug": ("name",)}


class FloorInline(admin.TabularInline):
    model = Floor
    extra = 1


class GateInline(admin.TabularInline):
    model = Gate
    extra = 1


@admin.register(Building)
class BuildingAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "floors", "entry_gates", "exit_gates")
    list_filter = ("organization",)
    inlines = [FloorInline, GateInline]


@admin.register(Floor)
class FloorAdmin(admin.ModelAdmin):
    list_display = ("name", "building", "level")


@admin.register(Gate)
class GateAdmin(admin.ModelAdmin):
    list_display = ("name", "building", "gate_type")
    list_filter = ("gate_type",)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "organization")
    list_filter = ("organization",)


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ("employee_id", "user", "organization", "department", "designation", "status")
    list_filter = ("organization", "department", "status")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Read-only audit browser: the trail can be inspected, never edited here.

    ``readonly_fields`` already blocked edits, but add/change/delete were still
    permitted, so a staff user could backdate a row, invent one, or delete
    evidence.  They are denied outright.  This is protection at the application
    layer only -- it is not database-level immutability (see the model
    docstring), because neither a trigger nor a write-block is installed.
    """

    list_display = ("action", "user", "organization", "entity_type", "entity_id", "created_at")
    list_filter = ("action", "created_at", "organization")
    search_fields = ("action", "details", "user__email")
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
