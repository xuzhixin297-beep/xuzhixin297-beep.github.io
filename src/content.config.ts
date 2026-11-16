import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';
import { z } from "astro/zod";

const articles = defineCollection({
    loader: glob({
        pattern: "**/*.md",
        base: "./src/content/articles",
    }),

    schema: z.object({
        title: z.string(),
        description: z.string(),
        authors: z.array(z.string()),
        pubDate: z.coerce.date(),
        subjects: z.array(z.string()),
        tags: z.array(z.string()),
    }),
});

export const collections = {
    articles,
};