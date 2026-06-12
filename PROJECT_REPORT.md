# Modular Orbit: One-Page Project Report

## Project Summary

Modular Orbit is a personal AI life operating system. Its purpose is to help a person understand themselves more clearly, organize the important information from their life, make smarter decisions, prioritize meaningful work, and build a stronger, more intentional career. The project is designed around the idea that useful AI should not only answer questions in the moment, but also remember the person's goals, habits, aspirations, relationships, work, health, and evolving story over time.

## Core Purpose

The central goal of Modular Orbit is to turn scattered life data into useful self-knowledge and action. A person can capture thoughts, tasks, plans, logs, documents, and reflections without needing to perfectly organize them first. Orbit then connects that information to the person's User Model, goals, and story, so future conversations and recommendations become more context-aware.

This matters because important life and career decisions are rarely isolated. They depend on patterns: what the person values, what drains or energizes them, what goals they are committed to, what work matters most, what decisions they keep revisiting, and what kind of future they are trying to build. Modular Orbit is being built to make those patterns visible and usable.

## How The System Works

Orbit is organized around a stable lifecycle:

```text
Capture -> Life Item -> Connection Review -> Knowledge Chunks -> Story Buckets -> Context Chat
```

A capture is any new piece of life data, such as a task, journal-style log, document, plan, or chat-created idea. If accepted, it becomes a Life Item, which is the durable source of truth. Orbit then reviews how that item connects to goals, story buckets, other life items, and possible future actions. Some items also become retrievable knowledge so the AI can use them later in context-aware chat.

The User Model is the heart of the system. It is made of editable Story Buckets such as identity, career, aspirations, health, habits, relationships, and interests. These files represent what Orbit understands about the person, while still keeping the person in control through direct editing and confirmation.

## Current Product Shape

The project is a full-stack app with a FastAPI backend, React frontend, Postgres storage, pgvector-based retrieval, and Gemini-powered AI capabilities. It includes modules for Chat, Curious, Logs, Tasks, Routine, Plans, Documents, Goals, and the User Model. The architecture is intentionally modular so new life-data capabilities can be added without breaking the core lifecycle.

The most important user-facing moments are:

- **Capture:** quickly add life data without overthinking structure.
- **Focus:** see what matters next and why.
- **Decide:** compare options using goals and personal context.
- **Discuss:** talk with Orbit about a task, plan, document, or life question in context.

## Why This Project Matters

Modular Orbit is not just a productivity app. It is a system for building self-understanding and turning that understanding into better action. It can help the person notice recurring priorities, clarify goals, protect attention, make career choices with more confidence, and convert vague ambition into concrete plans.

The long-term vision is a trusted personal AI workspace that helps the person live and work with more direction. It should support smart life decisions, practical prioritization, and a propelling career by connecting day-to-day actions with deeper identity, values, and goals.

## Success Definition

The project succeeds when Orbit helps the person answer questions like:

- What should I focus on today?
- Which opportunity best fits my goals?
- What patterns do I keep repeating?
- What work will move my career forward?
- What does Orbit understand about me, and is it accurate?
- What should become a task, plan, document, goal, or reflection?

In short, Modular Orbit is being built to help a person understand themselves, choose better, act on what matters, and keep becoming the kind of person their future needs.
