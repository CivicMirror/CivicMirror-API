from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.utils.html import format_html, format_html_join
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import action, display
from unfold.forms import ActionForm
from unfold.widgets import UnfoldAdminTextareaWidget, UnfoldAdminTextInputWidget

from cm2_elections.models import Person
from cm2_review.workflow import add_review_note, supersede_review_case, transition_review_case

from .models import IdentityReviewCase, IdentityReviewSuggestion


class IdentityReviewSuggestionInline(TabularInline):
    model = IdentityReviewSuggestion
    extra = 0
    autocomplete_fields = ("suggested_person",)


class ReviewCaseActionForm(ActionForm):
    target_person_public_id = forms.CharField(
        required=False,
        widget=UnfoldAdminTextInputWidget(attrs={"size": 14, "placeholder": "person public id"}),
        help_text="Public ID of the target person for link/merge actions.",
    )
    target_case_public_id = forms.CharField(
        required=False,
        widget=UnfoldAdminTextInputWidget(attrs={"size": 14, "placeholder": "case public id"}),
        help_text="Public ID of the superseding case for the supersede action.",
    )
    note = forms.CharField(
        required=False,
        widget=UnfoldAdminTextareaWidget(attrs={"rows": 1, "cols": 20}),
        help_text="Note text for the add-note action.",
    )


@admin.register(IdentityReviewCase)
class IdentityReviewCaseAdmin(ModelAdmin):
    _REOPENABLE_STATUSES = {IdentityReviewCase.Status.OPEN, IdentityReviewCase.Status.DEFERRED}

    list_display = ("case_type_display", "status_display", "created_at", "reviewed_at", "reviewed_by", "has_private_evidence")
    list_filter = ("status", "case_type", "has_private_evidence")
    search_fields = ("public_id", "deduplication_key", "provisional_person__canonical_name")
    autocomplete_fields = (
        "source_record",
        "provisional_person",
        "result_choice",
        "reviewed_by",
        "superseded_by",
    )
    readonly_fields = (
        "id",
        "public_id",
        "deduplication_key",
        "created_at",
        "updated_at",
        "evidence_comparison",
        "status",
        "resolution_action",
        "reviewed_by",
        "reviewed_at",
        "superseded_by",
        "notes",
        "case_type",
        "has_private_evidence",
    )
    inlines = (IdentityReviewSuggestionInline,)
    action_form = ReviewCaseActionForm
    actions = (
        "confirm_new",
        "defer_cases",
        "reject_cases",
        "link_existing_cases",
        "merge_people_cases",
        "supersede_cases",
        "add_note_to_cases",
    )
    actions_row = ("confirm_new_row", "defer_case_row", "reject_case_row")
    actions_detail = ("confirm_new_row", "defer_case_row", "reject_case_row")
    fieldsets = (
        (None, {"fields": ("public_id", "case_type", "status", "has_private_evidence")}),
        ("Evidence comparison", {"fields": ("evidence_comparison",)}),
        (
            "Resolution",
            {"fields": ("resolution_action", "reviewed_by", "reviewed_at", "notes", "superseded_by")},
        ),
        ("Metadata", {"fields": ("id", "deduplication_key", "created_at", "updated_at")}),
    )

    @display(
        description="Case Type",
        ordering="case_type",
        label={
            IdentityReviewCase.CaseType.PERSON_IDENTITY: "info",
            IdentityReviewCase.CaseType.FUZZY_PERSON_MATCH: "warning",
            IdentityReviewCase.CaseType.UNRESOLVED_RESULT_CHOICE: "danger",
        },
    )
    def case_type_display(self, obj):
        return obj.get_case_type_display()

    @display(
        description="Status",
        ordering="status",
        label={
            IdentityReviewCase.Status.OPEN: "warning",
            IdentityReviewCase.Status.APPROVED: "success",
            IdentityReviewCase.Status.REJECTED: "danger",
            IdentityReviewCase.Status.DEFERRED: "info",
            IdentityReviewCase.Status.SUPERSEDED: "info",
        },
    )
    def status_display(self, obj):
        return obj.get_status_display()

    def _redirect_back(self, request):
        return redirect(request.META.get("HTTP_REFERER") or reverse("admin:cm2_review_identityreviewcase_changelist"))

    def get_urls(self):
        custom_urls = [
            path(
                "<path:object_id>/link-existing-suggestion/<uuid:suggestion_id>/",
                self.admin_site.admin_view(self.link_existing_suggestion),
                name="cm2_review_identityreviewcase_link_existing_suggestion",
            ),
            path(
                "<path:object_id>/merge-people-suggestion/<uuid:suggestion_id>/",
                self.admin_site.admin_view(self.merge_people_suggestion),
                name="cm2_review_identityreviewcase_merge_people_suggestion",
            ),
        ]
        return custom_urls + super().get_urls()

    def link_existing_suggestion(self, request, object_id, suggestion_id):
        return self._apply_suggestion_action(
            request,
            object_id,
            suggestion_id,
            action=IdentityReviewCase.ResolutionAction.LINK_EXISTING,
            verb="Linked to",
        )

    def merge_people_suggestion(self, request, object_id, suggestion_id):
        return self._apply_suggestion_action(
            request,
            object_id,
            suggestion_id,
            action=IdentityReviewCase.ResolutionAction.MERGE_PEOPLE,
            verb="Merged into",
        )

    def _apply_suggestion_action(self, request, object_id, suggestion_id, *, action, verb):
        review_case = get_object_or_404(IdentityReviewCase, pk=object_id)
        change_url = reverse("admin:cm2_review_identityreviewcase_change", args=[review_case.pk])
        suggestion = get_object_or_404(IdentityReviewSuggestion, pk=suggestion_id, review_case=review_case)
        if suggestion.suggested_person is None:
            self.message_user(request, "This suggestion has no linked person to target.", messages.ERROR)
            return redirect(change_url)
        if review_case.status not in self._REOPENABLE_STATUSES:
            self.message_user(request, "This case is not open or deferred.", messages.WARNING)
            return redirect(change_url)
        try:
            transition_review_case(
                review_case,
                reviewer=request.user,
                status=IdentityReviewCase.Status.APPROVED,
                action=action,
                target_person=suggestion.suggested_person,
            )
        except ValidationError as exc:
            self.message_user(request, "; ".join(exc.messages), messages.ERROR)
            return redirect(change_url)
        self.message_user(request, f"{verb} {suggestion.suggested_person.canonical_name}.", messages.SUCCESS)
        return redirect(change_url)

    @action(description="Confirm as distinct person")
    def confirm_new_row(self, request, object_id):
        review_case = IdentityReviewCase.objects.get(pk=object_id)
        if review_case.status in self._REOPENABLE_STATUSES:
            transition_review_case(
                review_case,
                reviewer=request.user,
                status=IdentityReviewCase.Status.APPROVED,
                action=IdentityReviewCase.ResolutionAction.CONFIRM_NEW,
            )
            self.message_user(request, "Confirmed as a distinct person.", messages.SUCCESS)
        else:
            self.message_user(request, "This case is not open or deferred.", messages.WARNING)
        return self._redirect_back(request)

    @action(description="Defer")
    def defer_case_row(self, request, object_id):
        review_case = IdentityReviewCase.objects.get(pk=object_id)
        if review_case.status == IdentityReviewCase.Status.OPEN:
            transition_review_case(
                review_case,
                reviewer=request.user,
                status=IdentityReviewCase.Status.DEFERRED,
                action=IdentityReviewCase.ResolutionAction.DEFER,
            )
            self.message_user(request, "Deferred.", messages.SUCCESS)
        else:
            self.message_user(request, "Only open cases can be deferred.", messages.WARNING)
        return self._redirect_back(request)

    @action(description="Reject")
    def reject_case_row(self, request, object_id):
        review_case = IdentityReviewCase.objects.get(pk=object_id)
        if review_case.status in self._REOPENABLE_STATUSES:
            transition_review_case(
                review_case,
                reviewer=request.user,
                status=IdentityReviewCase.Status.REJECTED,
                action=IdentityReviewCase.ResolutionAction.REJECT,
            )
            self.message_user(request, "Rejected.", messages.SUCCESS)
        else:
            self.message_user(request, "This case is not open or deferred.", messages.WARNING)
        return self._redirect_back(request)

    @admin.display(description="Evidence comparison")
    def evidence_comparison(self, obj):
        if obj.case_type == IdentityReviewCase.CaseType.FUZZY_PERSON_MATCH:
            suggestions = list(obj.suggestions.select_related("suggested_person").order_by("rank"))
            if obj.source_record is not None and suggestions:
                return self._fuzzy_match_comparison(obj, suggestions)
        return self._default_evidence_table(obj)

    def _default_evidence_table(self, obj):
        rows = []
        if obj.provisional_person is not None:
            rows.append(("Provisional person", obj.provisional_person.canonical_name))
        source = obj.source_record
        if source is not None:
            rows.append(("Source reported name", source.reported_name))
            rows.append(("Source ballot name", source.ballot_name or "—"))
            rows.append(("Protected address", source.protected_address or "—"))
            rows.append(("Protected phone", source.protected_phone or "—"))
            rows.append(("Protected email", source.protected_email or "—"))
        rows.append(("Supporting evidence", obj.supporting_evidence or {}))
        rows.append(("Conflicting evidence", obj.conflicting_evidence or {}))
        row_html = format_html_join(
            "\n",
            "<tr><th style='text-align:left;padding-right:1em;vertical-align:top'>{}</th><td>{}</td></tr>",
            ((label, value) for label, value in rows),
        )
        return format_html("<table>{}</table>", row_html)

    _FUZZY_NAME_FIELDS = (
        ("Name", "reported_name", "canonical_name"),
        ("Given name", "given_name", "given_name"),
        ("Middle name", "middle_name", "middle_name"),
        ("Family name", "family_name", "family_name"),
        ("Suffix", "suffix", "suffix"),
    )
    _FUZZY_CONTACT_FIELDS = (
        ("Ballot name", "ballot_name"),
        ("Protected address", "protected_address"),
        ("Protected phone", "protected_phone"),
        ("Protected email", "protected_email"),
    )

    def _fuzzy_match_comparison(self, obj, suggestions):
        source = obj.source_record
        cards = format_html_join(
            "\n",
            "{}",
            ((self._fuzzy_match_card(obj, source, suggestion),) for suggestion in suggestions),
        )
        return format_html(
            '<div class="rounded-default border border-base-200 dark:border-base-800 bg-base-50 '
            'dark:bg-base-900/60 p-3 mb-4 text-sm text-base-600 dark:text-base-400">'
            "New person found in <strong>{}</strong> — compared below against each possible existing "
            "match. Highlighted cells show a spelling difference; red cells show info present on only "
            "one side.</div>{}",
            source.reported_name if source is not None else "the source record",
            cards,
        )

    def _fuzzy_match_card(self, obj, source, suggestion):
        person = suggestion.suggested_person
        source_row = self._fuzzy_match_source_row(source, person)
        field_rows = format_html_join(
            "\n",
            "{}",
            (
                (self._fuzzy_match_row(label, getattr(source, source_attr, "") or "", getattr(person, person_attr, "") or "" if person else ""),)
                for label, source_attr, person_attr in self._FUZZY_NAME_FIELDS
            ),
        )
        contact_rows = format_html_join(
            "\n",
            "{}",
            (
                (self._fuzzy_match_row(label, getattr(source, source_attr, "") or "", "", right_label="Not tracked on existing person"),)
                for label, source_attr in self._FUZZY_CONTACT_FIELDS
            ),
        )
        score = f"{suggestion.score:.0%}" if suggestion.score is not None else "—"
        header = format_html(
            '<div class="flex items-center justify-between px-4 py-2 bg-base-50 dark:bg-base-800 '
            'border-b border-base-200 dark:border-base-700 rounded-t-default">'
            '<div class="font-semibold text-sm text-base-900 dark:text-base-100">'
            "Rank {} match — {}</div>"
            '<div class="text-xs text-base-500 dark:text-base-400">Score {}{}</div></div>',
            suggestion.rank,
            person.canonical_name if person else "(no linked person)",
            score,
            format_html(" · {}", suggestion.external_scheme) if suggestion.external_scheme else "",
        )
        column_headers = format_html(
            '<tr class="text-left text-xs uppercase text-base-400 dark:text-base-500 '
            'border-b border-base-200 dark:border-base-800">'
            '<th class="py-1 pr-2 font-medium">{}</th>'
            '<th class="py-1 pr-2 font-medium">{}</th>'
            '<th class="py-1 font-medium">{}</th></tr>',
            "Field",
            "New person found",
            "Existing possible match",
        )
        body = format_html(
            '<div class="p-3"><table class="w-full text-sm"><thead>{}</thead><tbody>{}{}{}</tbody></table></div>',
            column_headers,
            source_row,
            field_rows,
            contact_rows,
        )
        evidence = self._fuzzy_match_evidence(suggestion)
        footer = self._fuzzy_match_actions(obj, suggestion)
        return format_html(
            '<div class="rounded-default border border-base-200 dark:border-base-800 bg-white '
            'dark:bg-base-900 shadow-xs mb-4 overflow-hidden">{}{}{}{}</div>',
            header,
            body,
            evidence,
            footer,
        )

    def _fuzzy_match_actions(self, obj, suggestion):
        if suggestion.suggested_person is None:
            return ""
        if obj.status not in self._REOPENABLE_STATUSES:
            return ""
        link_url = reverse(
            "admin:cm2_review_identityreviewcase_link_existing_suggestion",
            args=[obj.pk, suggestion.pk],
        )
        merge_url = reverse(
            "admin:cm2_review_identityreviewcase_merge_people_suggestion",
            args=[obj.pk, suggestion.pk],
        )
        return format_html(
            '<div class="flex items-center gap-2 px-4 py-2 border-t border-base-200 dark:border-base-800">'
            '<a href="{}" class="inline-flex items-center rounded-default border border-base-300 '
            'dark:border-base-700 bg-base-100 dark:bg-base-800 px-2 py-1 text-xs font-medium '
            'text-base-700 dark:text-base-200 hover:bg-base-200 dark:hover:bg-base-700">'
            "Link existing to {}</a>"
            '<a href="{}" class="inline-flex items-center rounded-default bg-primary-600 '
            'hover:bg-primary-700 px-2 py-1 text-xs font-medium text-white">'
            "Merge people into {}</a></div>",
            link_url,
            suggestion.suggested_person.canonical_name,
            merge_url,
            suggestion.suggested_person.canonical_name,
        )

    def _source_artifact_link(self, artifact):
        if artifact is None:
            return format_html(
                '<span class="text-base-400 dark:text-base-600 italic">{}</span>', "Unknown source"
            )
        url = reverse("admin:cm2_core_sourceartifact_change", args=[artifact.pk])
        description = f"{artifact.source_system} · {artifact.get_source_type_display()}"
        retrieved = artifact.retrieved_at.strftime("%b %-d, %Y") if artifact.retrieved_at else None
        return format_html(
            '<a href="{}" class="text-primary-600 dark:text-primary-400 underline">{}</a>{}',
            url,
            description,
            format_html(" · retrieved {}", retrieved) if retrieved else "",
        )

    def _fuzzy_match_source_row(self, source, person):
        left = self._source_artifact_link(source.source_artifact if source is not None else None)
        right = self._source_artifact_link(person.source_artifact if person is not None else None)
        return format_html(
            '<tr class="border-b border-base-100 dark:border-base-900 bg-base-100 dark:bg-base-800">'
            '<td class="py-1 pr-2 text-base-500 dark:text-base-400 align-top">Source</td>'
            '<td class="py-1 pr-2 align-top">{}</td><td class="py-1 align-top">{}</td></tr>',
            left,
            right,
        )

    def _fuzzy_match_row(self, label, left_value, right_value, *, right_label=None):
        left = (left_value or "").strip()
        right = (right_value or "").strip()
        base_cell = "py-1 pr-2 align-top"
        if not left and not right:
            left_display, left_class = "—", base_cell
            right_display, right_class = right_label or "—", f"{base_cell} text-base-400 dark:text-base-600 italic"
        elif left and not right:
            left_display, left_class = left, base_cell
            right_display = right_label or "Missing"
            right_class = "py-1 align-top bg-red-50 dark:bg-red-900 text-red-600 dark:text-red-400 italic rounded px-1"
        elif right and not left:
            left_display, left_class = "Missing", "py-1 pr-2 align-top bg-red-50 dark:bg-red-900 text-red-600 dark:text-red-400 italic rounded px-1"
            right_display, right_class = right, base_cell.replace("pr-2 ", "")
        elif left.lower() != right.lower():
            left_display, left_class = left, "py-1 pr-2 align-top bg-orange-100 dark:bg-orange-900 text-orange-700 dark:text-orange-400 rounded px-1"
            right_display, right_class = right, "py-1 align-top bg-orange-100 dark:bg-orange-900 text-orange-700 dark:text-orange-400 rounded px-1"
        else:
            left_display, left_class = left, base_cell
            right_display, right_class = right, base_cell.replace("pr-2 ", "")
        return format_html(
            '<tr class="border-b border-base-100 dark:border-base-900">'
            '<td class="py-1 pr-2 text-base-500 dark:text-base-400 align-top">{}</td>'
            '<td class="{}">{}</td><td class="{}">{}</td></tr>',
            label,
            left_class,
            left_display,
            right_class,
            right_display,
        )

    def _fuzzy_match_evidence(self, suggestion):
        parts = []
        if suggestion.supporting_evidence:
            parts.append(("Supporting evidence", suggestion.supporting_evidence, "text-green-700 dark:text-green-400"))
        if suggestion.conflicting_evidence:
            parts.append(("Conflicting evidence", suggestion.conflicting_evidence, "text-red-600 dark:text-red-400"))
        if not parts:
            return ""
        rows = format_html_join(
            "\n",
            '<div class="px-4 py-2"><div class="text-xs font-semibold uppercase {}">{}</div>'
            '<div class="text-sm text-base-600 dark:text-base-400">{}</div></div>',
            ((cls, label, value) for label, value, cls in parts),
        )
        return format_html(
            '<div class="border-t border-base-200 dark:border-base-800 divide-y divide-base-100 '
            'dark:divide-base-900">{}</div>',
            rows,
        )

    @admin.action(description="Confirm selected cases as distinct people")
    def confirm_new(self, request, queryset):
        total = queryset.count()
        updated = 0
        for review_case in queryset.filter(status__in=self._REOPENABLE_STATUSES):
            transition_review_case(
                review_case,
                reviewer=request.user,
                status=IdentityReviewCase.Status.APPROVED,
                action=IdentityReviewCase.ResolutionAction.CONFIRM_NEW,
            )
            updated += 1
        skipped = total - updated
        if skipped:
            self.message_user(
                request,
                f"Confirmed {updated} review case(s); {skipped} skipped (not open or deferred).",
                messages.WARNING,
            )
        else:
            self.message_user(request, f"Confirmed {updated} review case(s).", messages.SUCCESS)

    @admin.action(description="Defer selected review cases")
    def defer_cases(self, request, queryset):
        updated = 0
        for review_case in queryset.filter(status=IdentityReviewCase.Status.OPEN):
            transition_review_case(
                review_case,
                reviewer=request.user,
                status=IdentityReviewCase.Status.DEFERRED,
                action=IdentityReviewCase.ResolutionAction.DEFER,
            )
            updated += 1
        self.message_user(request, f"Deferred {updated} review case(s).", messages.SUCCESS)

    @admin.action(description="Reject selected review cases (disputes the provisional person)")
    def reject_cases(self, request, queryset):
        total = queryset.count()
        updated = 0
        for review_case in queryset.filter(status__in=self._REOPENABLE_STATUSES):
            transition_review_case(
                review_case,
                reviewer=request.user,
                status=IdentityReviewCase.Status.REJECTED,
                action=IdentityReviewCase.ResolutionAction.REJECT,
            )
            updated += 1
        skipped = total - updated
        if skipped:
            self.message_user(
                request,
                f"Rejected {updated} review case(s); {skipped} skipped (not open or deferred).",
                messages.WARNING,
            )
        else:
            self.message_user(request, f"Rejected {updated} review case(s).", messages.SUCCESS)

    @admin.action(description="Link selected cases to target person (enter target person public ID above)")
    def link_existing_cases(self, request, queryset):
        target_person = self._resolve_target_person(request)
        if target_person is None:
            return
        total = queryset.count()
        updated, failed, errors = self._apply_bulk_action(
            queryset.filter(status__in=self._REOPENABLE_STATUSES),
            lambda review_case: transition_review_case(
                review_case,
                reviewer=request.user,
                status=IdentityReviewCase.Status.APPROVED,
                action=IdentityReviewCase.ResolutionAction.LINK_EXISTING,
                target_person=target_person,
            ),
        )
        skipped = total - updated - failed
        self._report_bulk_result(
            request,
            success_verb=f"Linked {updated} review case(s) to {target_person.canonical_name}",
            failure_verb="could not be linked",
            failed=failed,
            errors=errors,
            skipped=skipped,
        )

    @admin.action(description="Merge selected cases into target person (enter target person public ID above)")
    def merge_people_cases(self, request, queryset):
        target_person = self._resolve_target_person(request)
        if target_person is None:
            return
        total = queryset.count()
        updated, failed, errors = self._apply_bulk_action(
            queryset.filter(status__in=self._REOPENABLE_STATUSES),
            lambda review_case: transition_review_case(
                review_case,
                reviewer=request.user,
                status=IdentityReviewCase.Status.APPROVED,
                action=IdentityReviewCase.ResolutionAction.MERGE_PEOPLE,
                target_person=target_person,
            ),
        )
        skipped = total - updated - failed
        self._report_bulk_result(
            request,
            success_verb=f"Merged {updated} review case(s) into {target_person.canonical_name}",
            failure_verb="could not be merged",
            failed=failed,
            errors=errors,
            skipped=skipped,
        )

    @admin.action(description="Supersede selected cases with target case (enter target case public ID above)")
    def supersede_cases(self, request, queryset):
        target_public_id = request.POST.get("target_case_public_id", "").strip()
        if not target_public_id:
            self.message_user(request, "Provide a target case public ID to supersede with.", messages.ERROR)
            return
        target_case = IdentityReviewCase.objects.filter(public_id=target_public_id).first()
        if target_case is None:
            self.message_user(request, f"No review case found with public ID {target_public_id}.", messages.ERROR)
            return
        updated, failed, errors = self._apply_bulk_action(
            queryset,
            lambda review_case: supersede_review_case(review_case, superseded_by=target_case, actor=request.user),
        )
        self._report_bulk_result(
            request,
            success_verb=f"Superseded {updated} review case(s)",
            failure_verb="could not be superseded",
            failed=failed,
            errors=errors,
        )

    @admin.action(description="Add note to selected open/deferred cases (enter note text above)")
    def add_note_to_cases(self, request, queryset):
        note = request.POST.get("note", "").strip()
        if not note:
            self.message_user(request, "Provide note text to add a note.", messages.ERROR)
            return
        excluded_statuses = [
            IdentityReviewCase.Status.APPROVED,
            IdentityReviewCase.Status.REJECTED,
            IdentityReviewCase.Status.SUPERSEDED,
        ]
        updated, failed, errors = self._apply_bulk_action(
            queryset.exclude(status__in=excluded_statuses),
            lambda review_case: add_review_note(review_case, actor=request.user, note=note),
        )
        self._report_bulk_result(
            request,
            success_verb=f"Added a note to {updated} review case(s)",
            failure_verb="could not receive the note",
            failed=failed,
            errors=errors,
        )

    def _apply_bulk_action(self, queryset, apply_fn):
        """Run apply_fn per item, isolating ValidationErrors so one bad case doesn't abort the batch."""
        updated = 0
        failed = 0
        errors = []
        for review_case in queryset:
            try:
                apply_fn(review_case)
            except ValidationError as exc:
                failed += 1
                errors.append(f"{review_case.public_id}: {'; '.join(exc.messages)}")
            else:
                updated += 1
        return updated, failed, errors

    def _report_bulk_result(self, request, *, success_verb, failure_verb, failed, errors, skipped=0):
        skipped_note = f"; {skipped} skipped (not open or deferred)" if skipped else ""
        if failed:
            detail = " | ".join(errors)
            self.message_user(
                request,
                f"{success_verb}{skipped_note}; {failed} review case(s) {failure_verb}: {detail}",
                messages.WARNING,
            )
        elif skipped:
            self.message_user(request, f"{success_verb}{skipped_note}.", messages.WARNING)
        else:
            self.message_user(request, f"{success_verb}.", messages.SUCCESS)

    def _resolve_target_person(self, request):
        target_public_id = request.POST.get("target_person_public_id", "").strip()
        if not target_public_id:
            self.message_user(request, "Provide a target person public ID for this action.", messages.ERROR)
            return None
        target_person = Person.objects.filter(public_id=target_public_id).first()
        if target_person is None:
            self.message_user(request, f"No person found with public ID {target_public_id}.", messages.ERROR)
            return None
        return target_person


@admin.register(IdentityReviewSuggestion)
class IdentityReviewSuggestionAdmin(ModelAdmin):
    list_display = ("review_case", "rank", "suggested_person", "external_scheme", "uses_private_evidence")
    list_filter = ("external_scheme", "uses_private_evidence")
    search_fields = ("review_case__public_id", "suggested_person__canonical_name", "external_identifier")
    autocomplete_fields = ("review_case", "suggested_person")
