import { defineSchema, defineTable } from "convex/server";
import { v } from "convex/values";

const jobStatus = v.union(
  v.literal("new"),
  v.literal("filtered_out"),
  v.literal("scored"),
  v.literal("applied"),
  v.literal("skipped"),
  v.literal("error"),
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
    match_reason: v.optional(v.string()),
    salary: v.optional(v.string()),
    summary: v.optional(v.string()),
    status: jobStatus,
    created_at: v.number(),

  }).index("by_source_external", ["source", "external_id"])
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

  logs: defineTable({
    level: v.union(v.literal("info"), v.literal("warn"), v.literal("error")),
    message: v.string(),
    context: v.optional(v.any()),
    created_at: v.number(),
  }),
});