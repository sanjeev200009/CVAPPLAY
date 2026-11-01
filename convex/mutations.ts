import { mutation } from "./_generated/server";
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

export const upsertJob = mutation({
  args: {
    job: v.object({
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
      status: jobStatus,
      created_at: v.number(),
    }),
  },
  handler: async (ctx, { job }) => {
    const existing = await ctx.db
      .query("jobs")
      .withIndex("by_source_external", (q) =>
        q.eq("source", job.source).eq("external_id", job.external_id),
      )
      .first();
    if (existing) {
      return { id: existing._id, created: false };
    }
    const id = await ctx.db.insert("jobs", job);
    return { id, created: true };
  },
});

export const updateJob = mutation({
  args: {
    job_id: v.id("jobs"),
    status: v.optional(jobStatus),
    match_score: v.optional(v.number()),
    match_tier: v.optional(v.string()),
    match_reason: v.optional(v.string()),
    salary: v.optional(v.string()),
    summary: v.optional(v.string()),
    manual_review_reason: v.optional(v.string()),
    clear_score: v.optional(v.boolean()),
  },
  handler: async (ctx, { job_id, status, match_score, match_tier, match_reason, salary, summary, manual_review_reason, clear_score }) => {
    const patch: Record<string, unknown> = {};
    if (status !== undefined) patch.status = status;
    if (match_score !== undefined) patch.match_score = match_score;
    if (match_tier !== undefined) patch.match_tier = match_tier;
    if (match_reason !== undefined) patch.match_reason = match_reason;
    if (salary !== undefined) patch.salary = salary;
    if (summary !== undefined) patch.summary = summary;
    if (manual_review_reason !== undefined) patch.manual_review_reason = manual_review_reason;
    // Reset back to unscored: pendingScoring re-picks jobs whose match_score
    // is undefined, so a plain re-queue must actually remove the field.
    if (clear_score) {
      patch.match_score = undefined;
      patch.match_tier = undefined;
      patch.match_reason = undefined;
    }
    await ctx.db.patch(job_id, patch);
  },
});


export const insertLog = mutation({
  args: {
    level: v.union(v.literal("info"), v.literal("warn"), v.literal("error")),
    message: v.string(),
    context: v.optional(v.any()),
    created_at: v.number(),
  },
  handler: async (ctx, args) => {
    await ctx.db.insert("logs", args);
  },
});

export const insertApplication = mutation({
  args: {
    job_id: v.id("jobs"),
    cover_letter: v.optional(v.string()),
    submitted_at: v.optional(v.number()),
    submission_status: v.optional(
      v.union(v.literal("success"), v.literal("failed")),
    ),
    error_message: v.optional(v.string()),
    form_payload: v.optional(v.any()),
  },
  handler: async (ctx, args) => {
    return await ctx.db.insert("applications", args);
  },
});

export const insertResumeVersion = mutation({
  args: {
    version_label: v.string(),
    content_text: v.optional(v.string()),
    file_url: v.optional(v.string()),
    active: v.boolean(),
  },
  handler: async (ctx, args) => {
    return await ctx.db.insert("resume_versions", args);
  },
});

export const insertDailyReport = mutation({
  args: {
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
  },
  handler: async (ctx, args) => {
    return await ctx.db.insert("daily_reports", args);
  },
});

export const clearAllJobs = mutation({
  args: {},
  handler: async (ctx) => {
    const jobs = await ctx.db.query("jobs").collect();
    for (const job of jobs) {
      await ctx.db.delete(job._id);
    }
    return jobs.length;
  },
});

export const resetScoring = mutation({
  args: {},
  handler: async (ctx) => {
    const jobs = await ctx.db.query("jobs").collect();
    let n = 0;
    for (const job of jobs) {
      if (job.status === "scored" || job.match_score !== undefined) {
        await ctx.db.patch(job._id, {
          status: "new",
          match_score: undefined,
          match_reason: undefined,
        });
        n += 1;
      }
    }
    return n;
  },
});

export const markDeadEmail = mutation({
  args: {
    address: v.string(),
    reason: v.optional(v.string()),
    source: v.optional(v.string()),
  },
  handler: async (ctx, { address, reason, source }) => {
    const addr = address.toLowerCase().trim();
    const existing = await ctx.db
      .query("dead_emails")
      .withIndex("by_address", (q) => q.eq("address", addr))
      .first();
    if (existing) return false;
    await ctx.db.insert("dead_emails", {
      address: addr,
      reason,
      source,
      first_seen: Date.now(),
    });
    return true;
  },
});
