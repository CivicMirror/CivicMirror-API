from django.contrib import admin

from .models import Candidate, DistrictRecord, Election, ElectionCycle, MeasureOption, Race


@admin.register(ElectionCycle)
class ElectionCycleAdmin(admin.ModelAdmin):
    list_display = ('cycle_year', 'description', 'cycle_start', 'cycle_end')
    ordering = ('-cycle_year',)


@admin.register(Election)
class ElectionAdmin(admin.ModelAdmin):
    list_display = ('name', 'election_date', 'jurisdiction_level', 'state', 'status', 'last_synced_at')
    list_filter = ('status', 'jurisdiction_level', 'state')
    search_fields = ('name', 'source_id', 'state')
    readonly_fields = ('last_synced_at',)
    ordering = ('-election_date',)


@admin.register(Race)
class RaceAdmin(admin.ModelAdmin):
    list_display = ('office_title', 'election', 'race_type', 'source', 'certification_status', 'race_status')
    list_filter = ('race_type', 'source', 'certification_status', 'race_status')
    search_fields = ('office_title', 'jurisdiction', 'ocd_division_id')
    raw_id_fields = ('election',)
    readonly_fields = ('last_synced_at', 'normalized_office_title', 'canonical_key')


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display = ('name', 'party', 'race', 'incumbent', 'candidate_status')
    list_filter = ('candidate_status', 'incumbent')
    search_fields = ('name', 'party', 'fec_candidate_id', 'bioguide_id')
    raw_id_fields = ('race',)


@admin.register(MeasureOption)
class MeasureOptionAdmin(admin.ModelAdmin):
    list_display = ('option_label', 'race')
    raw_id_fields = ('race',)


@admin.register(DistrictRecord)
class DistrictRecordAdmin(admin.ModelAdmin):
    list_display = ('name', 'state', 'district_type', 'ocd_division_id', 'fips_code')
    list_filter = ('state', 'district_type')
    search_fields = ('name', 'ocd_division_id', 'fips_code')
