import { query } from "./_generated/server";
import { v } from "convex/values";

export const jobByExternal = query({
  args: { source: v.string(), external_id: v.string() },
  handler: async (ctx, { source, external_id }) => {
    return await ctx.db
      .query("jobs")
      .withIndex("by_source_external", (q) =>
        q.eq("source", source).eq("external_id", external_id),
      )
      .first();
  },
});

export const jobStats = query({
  args: {},
  handler: async (ctx) => {
    const jobs = await ctx.db.query("jobs").collect();
    const counts: Record<string, number> = {};
    for (const job of jobs) {
      counts[job.status] = (counts[job.status] ?? 0) + 1;
    }
    return { total: jobs.length, counts };
  },
});

export const recentLogs = query({
  args: { limit: v.number() },
  handler: async (ctx, { limit }) => {
    return await ctx.db
      .query("logs")
      .order("desc")
      .take(Math.min(limit, 100));
  },
});

export const recentJobs = query({
  args: { limit: v.number() },
  handler: async (ctx, { limit }) => {
    return await ctx.db
      .query("jobs")
      .withIndex("by_status", (q) => q.eq("status", "new"))
      .order("desc")
      .take(Math.min(limit, 100));
  },
});

export const pendingScoring = query({
  args: { limit: v.number() },
  handler: async (ctx, { limit }) => {
    const jobs = await ctx.db
      .query("jobs")
      .withIndex("by_status", (q) => q.eq("status", "new"))
      .order("desc")
      .take(200);
    return jobs
      .filter((job) => job.match_score === undefined)
      .slice(0, Math.min(limit, 200));
  },
});

export const scoredJobs = query({
  args: { limit: v.number() },
  handler: async (ctx, { limit }) => {
    const jobs = await ctx.db
      .query("jobs")
      .withIndex("by_status", (q) => q.eq("status", "scored"))
      .collect();
    return jobs
      .sort((a, b) => (b.match_score ?? 0) - (a.match_score ?? 0))
      .slice(0, Math.min(limit, 500));
  },
});


export const applicationsSince = query({
  args: { since: v.number() },
  handler: async (ctx, { since }) => {
    const apps = await ctx.db.query("applications").collect();
    return apps.filter((app) => (app.submitted_at ?? 0) >= since);
  },
});