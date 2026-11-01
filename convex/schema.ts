import { defineSchema, defineTable } from "convex/server";
import { v } from "convex/values";

const jobStatus = v.union(
  v.literal("new"),
  v.literal("filtered_out"),
  v.literal("scored"),
  v.literal("applied"),
  v.literal("skipped"),
  v.literal("error"),
  v.literal("manual_review"),
  v.literal("invalid"),
);

export default defineSchema({
  jobs: defineTable({
    source: v.string(),
    external_id: v.string(),
    company: v.string(),
    title: v.string(),
    location: v.string(),
    remote: v.boolean(),
    location_tier: v.optional(v.string()),
    description: v.string(),
    apply_url: v.string(),
    posted_at: v.optional(v.number()),
    match_score: v.optional(v.number()),
    match_tier: v.optional(v.string()),       // "A" | "B" | "C"
    match_reason: v.optional(v.string()),
    salary: v.optional(v.string()),
    summary: v.optional(v.string()),
    status: jobStatus,
    manual_review_reason: v.optional(v.string()),
    created_at: v.number(),
  })
    .index("by_source_external", ["source", "external_id"])
    .index("by_status", ["status"])
    .index("by_tier", ["location_tier", "status"]),

  applications: defineTable({
    job_id: v.id("jobs"),
    cover_letter: v.optional(v.string()),
    submitted_at: v.optional(v.number()),
    submission_status: v.optional(
      v.union(v.literal("success"), v.literal("failed")),
    ),
    error_message: v.optional(v.string()),
    form_payload: v.optional(v.any()),
  }),

  resume_versions: defineTable({
    version_label: v.string(),
    content_text: v.optional(v.string()),
    file_url: v.optional(v.string()),
    active: v.boolean(),
  }),

  // Addresses that returned a permanent delivery failure. Lives in the DB, not
  // on disk: the 24/7 GitHub Actions runner is ephemeral, so a local file would
  // relearn the same dead addresses on every run.
  dead_emails: defineTable({
    address: v.string(),
    reason: v.optional(v.string()),
    source: v.optional(v.string()),
    first_seen: v.number(),
  }).index("by_address", ["address"]),

  logs: defineTable({
    level: v.union(v.literal("info"), v.literal("warn"), v.literal("error")),
    message: v.string(),
    context: v.optional(v.any()),
    created_at: v.number(),
  }),

  daily_reports: defineTable({
    run_at: v.number(),
    jobs_found: v.number(),
    jobs_filtered: v.number(),
    jobs_invalid: v.number(),
    jobs_relevant: v.number(),
    tier_a_count: v.number(),
    tier_b_count: v.number(),
    tier_c_count: v.number(),
    applications_submitted: v.number(),
    applications_manual: v.number(),
    applications_failed: v.number(),
    avg_match_score: v.number(),
    new_companies: v.array(v.string()),
    best_opportunities: v.array(v.string()),
    source_breakdown: v.optional(v.any()),
    problems: v.array(v.string()),
  }).index("by_run_at", ["run_at"]),
});
