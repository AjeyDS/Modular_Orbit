const DIRECT_API_BASE = ((import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://127.0.0.1:8000').replace(
  /\/$/,
  '',
)
const API_BASES = import.meta.env.DEV ? ['/api', DIRECT_API_BASE] : ['/api']

export type LifecycleStatus = 'active' | 'completed' | 'archived' | 'deleted'
export type AsyncStepStatus = 'pending' | 'complete' | 'failed' | 'not_needed'

export interface ModuleCatalogItem {
  id: string
  name: string
  description: string
  roles: string[]
  storage_strategy: 'generalized' | 'extended'
  valid_lifecycle_statuses: LifecycleStatus[]
  frontend_blocks: FrontendBlock[]
  default_settings: Record<string, unknown>
}

export interface FrontendBlock {
  block_id: string
  name: string
  size: 'small' | 'medium' | 'large' | 'wide' | 'full'
  description: string
}

export interface ModuleInstanceItem {
  id: string
  module_id: string
  module_name: string
  display_name: string
  enabled: boolean
  settings: Record<string, unknown>
  frontend_blocks: FrontendBlock[]
}

export interface DashboardBlock extends FrontendBlock {
  module_id: string
  module_instance_id: string
}

export interface ShellState {
  enabled_modules: ModuleInstanceItem[]
  sidebar: Array<{ module_instance_id: string; module_id: string; label: string }>
  dashboard_blocks: DashboardBlock[]
}

export interface LogItem {
  id: string
  title: string
  text: string
  lifecycle_status: Extract<LifecycleStatus, 'active' | 'archived' | 'deleted'>
  connection_status: AsyncStepStatus
  chunk_status: AsyncStepStatus
  bucket_update_status: AsyncStepStatus
  occurred_at: string
  created_at: string
  updated_at: string
}

export interface CreateLogRequest {
  text: string
  title?: string
}

export interface TaskItem {
  id: string
  title: string
  description: string
  lifecycle_status: LifecycleStatus
  connection_status: AsyncStepStatus
  chunk_status: AsyncStepStatus
  bucket_update_status: AsyncStepStatus
  due_window: 'this_week' | 'this_month' | 'someday' | 'exact'
  due_date: string | null
  priority: number | null
  module_status: string | null
  completed_at: string | null
  original_title: string | null
  original_description: string | null
  rewrite_status: 'complete' | 'skipped' | string
  created_at: string
  updated_at: string
}

export interface TaskPrioritySuggestionEntry {
  task_id: string
  title: string
  reason: string
}

export interface TaskPrioritySuggestionState {
  id: string | null
  status: 'empty' | 'active' | 'invalidated' | 'failed'
  suggestion_text: string
  ranked: TaskPrioritySuggestionEntry[]
  skippable: TaskPrioritySuggestionEntry[]
  sort_enabled: boolean
  panel_visible: boolean
  task_snapshot_hash: string
  context_summary: Record<string, unknown>
  created_at: string | null
  updated_at: string | null
}

export interface CreateTaskRequest {
  title: string
  description?: string
  due_window?: 'this_week' | 'this_month' | 'someday' | 'exact'
  due_date?: string | null
  priority?: number | null
  module_status?: string | null
}

export interface RoutineItem {
  id: string
  title: string
  description: string
  lifecycle_status: Extract<LifecycleStatus, 'active' | 'archived' | 'deleted'>
  connection_status: AsyncStepStatus
  chunk_status: AsyncStepStatus
  bucket_update_status: AsyncStepStatus
  position: number
  today_completed: boolean
  streak_count: number
  created_at: string
  updated_at: string
}

export interface RoutineState {
  date: string
  total_count: number
  completed_count: number
  items: RoutineItem[]
}

export interface CreateRoutineRequest {
  title: string
  description?: string
  position?: number
}

export interface PlanStepItem {
  id: string
  parent_step_id: string | null
  position: number
  title: string
  description: string
  status: 'active' | 'completed' | 'archived'
  completed_at: string | null
  children?: PlanStepItem[]
}

export interface PlanItem {
  id: string
  title: string
  description: string
  lifecycle_status: LifecycleStatus
  connection_status: AsyncStepStatus
  chunk_status: AsyncStepStatus
  bucket_update_status: AsyncStepStatus
  progress_percent: number
  completed_steps: number
  total_steps: number
  completed_at: string | null
  steps: PlanStepItem[]
  created_at: string
  updated_at: string
}

export interface CreatePlanRequest {
  title: string
  description?: string
  category?: 'work' | 'learn' | 'personal'
  raw_text?: string | null
  steps?: Array<{ title: string; description?: string; position?: number }>
  nodes?: ParsedPlanNode[]
}

export interface ParsedPlanNode {
  title: string
  description?: string | null
  metadata?: Record<string, unknown>
  children: ParsedPlanNode[]
}

export interface ParsedPlanDraft {
  title: string
  category: 'work' | 'learn' | 'personal'
  nodes: ParsedPlanNode[]
}

export interface DocumentItem {
  id: string
  title: string
  description: string
  lifecycle_status: Extract<LifecycleStatus, 'active' | 'archived' | 'deleted'>
  connection_status: AsyncStepStatus
  chunk_status: AsyncStepStatus
  bucket_update_status: AsyncStepStatus
  unique_name: string
  original_name: string
  mime_type: string
  byte_size: number
  content_sha256: string
  category_tag: string
  connection_summary: string
  tag_status: 'pending' | 'complete' | 'failed' | string
  created_at: string
  updated_at: string
}

export interface CreateDocumentRequest {
  original_name: string
  content: string
  unique_name?: string
  mime_type?: string
}

export type ChatMode = 'fast' | 'understanding'

export interface CaptureProposalPreview {
  id: string
  session_id: string
  module_id: string
  item_type: string
  title: string
  description: string
  payload: Record<string, unknown>
  confidence_bucket: 'low' | 'medium' | 'high'
  confidence_score: number
  explicit_request: boolean
  should_create_chunks: boolean
  should_create_bucket_update: boolean
  status: string
}

export interface ChatResponse {
  mode: ChatMode
  answer: string
  suggestions: CaptureProposalPreview[]
}

export interface ConfirmCaptureProposalResponse {
  proposal_id: string
  module_id: string
  life_item_id: string | null
  goal_id: string | null
  status: string
}

export type GoalHorizon = 'short_term' | 'long_term'
export type GoalStatus = 'active' | 'tentative'

export interface GoalItem {
  goal_id: string
  title: string
  body: string
  status: GoalStatus
  horizon: GoalHorizon
  target_date: string | null
  target_note: string | null
}

export interface GoalCreateRequest {
  title: string
  body?: string
  status?: GoalStatus
  horizon?: GoalHorizon
  target_date?: string | null
  target_note?: string | null
}

export interface GoalUpdateRequest {
  title?: string
  body?: string
  status?: GoalStatus
  horizon?: GoalHorizon
  target_date?: string | null
  target_note?: string | null
}

export interface ChatSessionItem {
  id: string
  title: string | null
  message_count: number
  last_message_at: string | null
  created_at: string
  updated_at: string
}

export interface ChatMessageItem {
  id: string
  session_id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  mode: ChatMode | null
  suggestions: CaptureProposalPreview[] | null
  created_at: string
}

export interface CuriousOption {
  id: string
  label: string
  bucket_update_text: string
}

export interface CuriousQuestion {
  id: string
  tier: 'onboarding' | 'bay' | 'dynamic'
  update_type: 'identity'
  foundational: boolean
  target_bucket_key: string
  target_bucket_id: string | null
  target_bucket_name: string
  framing_text: string
  question_text: string
  question_type: 'single_choice' | 'short_text'
  source_label: string
  sort_order: number
  options: CuriousOption[]
}

export interface CuriousAnswerSummary {
  question_id: string
  tier: 'onboarding' | 'bay' | 'dynamic'
  update_type: 'identity'
  foundational: boolean
  target_bucket_key: string
  target_bucket_name: string
  option_id: string
  response: string
  bucket_update_text: string
  life_item_id: string
}

export interface CuriousOnboardingState {
  session_id: string
  completed: boolean
  current_index: number
  question_count: number
  question: CuriousQuestion | null
  answers: CuriousAnswerSummary[]
}

export interface CuriousCompletion {
  session_id: string
  completed: boolean
  summary: CuriousAnswerSummary[]
  preview: Array<{ target_bucket_key: string; target_bucket_name: string; lines: string[] }>
}

export interface CuriousPendingQuestion {
  life_item_id: string | null
  question: CuriousQuestion
}

export interface CuriousAnsweredGroup {
  target_bucket_key: string
  target_bucket_name: string
  answers: CuriousAnswerSummary[]
}

export interface CuriousPageState {
  onboarding: CuriousOnboardingState
  pending_questions: CuriousPendingQuestion[]
  answered_groups: CuriousAnsweredGroup[]
  preview: Array<{ target_bucket_key: string; target_bucket_name: string; lines: string[] }>
  self_profile: string
  pending_count: number
}

export interface CuriousWeaveResult {
  results: Array<{
    story_bucket_id: string
    status: string
    merged_count: number
    superseded_count: number
    ignored_count: number
    file_path: string
  }>
}

export interface CompanionMessageItem {
  id: string
  role: 'assistant' | 'user'
  content: string
  meta: Record<string, unknown>
  created_at: string
}

export interface CompanionReply {
  kind: string
  message: string
  quick_replies: Array<{ id?: string; label: string }>
  target_bucket_key?: string | null
}

export interface CompanionState {
  messages: CompanionMessageItem[]
  pending_checkin: CompanionMessageItem | null
  settings: Record<string, unknown>
}

export interface CompanionMessageResponse {
  reply: CompanionReply
}

export interface StoryBucketItem {
  id: string
  stable_key: string
  file_path: string
  display_name: string
  description: string
  is_splittable: boolean
  status: 'active' | 'archived'
  content: string
  last_user_edit_at: string | null
  updated_at: string
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  let lastError = 'Network request failed'
  const isFormData = init?.body instanceof FormData

  for (const base of API_BASES) {
    const url = `${base}${path}`
    let response: Response
    try {
      response = await fetch(url, {
        headers: isFormData
          ? init?.headers
          : {
              'Content-Type': 'application/json',
              ...init?.headers,
            },
        ...init,
      })
    } catch (err) {
      lastError = err instanceof Error ? `${url}: ${err.message}` : `${url}: request failed`
      continue
    }

    if (!response.ok) {
      let detail = `${url}: ${response.status} ${response.statusText}`
      try {
        const body = await response.json()
        const bodyDetail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body)
        detail = `${url}: ${bodyDetail}`
      } catch {
        // Keep the status text fallback.
      }
      lastError = detail
      if (response.status === 404 || response.status >= 500) continue
      throw new Error(detail)
    }

    if (response.status === 204) return undefined as T
    return response.json() as Promise<T>
  }

  throw new Error(lastError)
}

export function fetchShellState(): Promise<ShellState> {
  return apiFetch<ShellState>('/shell/state')
}

export function fetchModuleCatalog(): Promise<ModuleCatalogItem[]> {
  return apiFetch<ModuleCatalogItem[]>('/shell/catalog')
}

export function enableModule(moduleId: string): Promise<ModuleInstanceItem> {
  return apiFetch<ModuleInstanceItem>(`/shell/modules/${moduleId}/enable`, { method: 'POST' })
}

export function disableModule(instanceId: string): Promise<ModuleInstanceItem> {
  return apiFetch<ModuleInstanceItem>(`/shell/instances/${instanceId}/disable`, { method: 'POST' })
}

export function updateModuleInstanceSettings(instanceId: string, settings: Record<string, unknown>): Promise<ModuleInstanceItem> {
  return apiFetch<ModuleInstanceItem>(`/shell/instances/${instanceId}/settings`, {
    method: 'PATCH',
    body: JSON.stringify({ settings }),
  })
}

export function restoreModuleInstanceSettings(instanceId: string): Promise<ModuleInstanceItem> {
  return apiFetch<ModuleInstanceItem>(`/shell/instances/${instanceId}/restore-defaults`, { method: 'POST' })
}

export function fetchLogs(): Promise<LogItem[]> {
  return apiFetch<LogItem[]>('/modules/logs')
}

export function createLog(payload: CreateLogRequest): Promise<LogItem> {
  return apiFetch<LogItem>('/modules/logs', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function archiveLog(logId: string): Promise<LogItem> {
  return apiFetch<LogItem>(`/modules/logs/${logId}/archive`, { method: 'POST' })
}

export function deleteLog(logId: string): Promise<void> {
  return apiFetch<void>(`/modules/logs/${logId}`, { method: 'DELETE' })
}

export function listGoals(): Promise<GoalItem[]> {
  return apiFetch<GoalItem[]>('/user-model/goals')
}

export function createGoal(payload: GoalCreateRequest): Promise<GoalItem> {
  return apiFetch<GoalItem>('/user-model/goals', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function updateGoal(goalId: string, payload: GoalUpdateRequest): Promise<GoalItem> {
  return apiFetch<GoalItem>(`/user-model/goals/${encodeURIComponent(goalId)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export function promoteGoal(goalId: string): Promise<GoalItem> {
  return apiFetch<GoalItem>(`/user-model/goals/${encodeURIComponent(goalId)}/promote`, {
    method: 'POST',
  })
}

export function deleteGoal(goalId: string): Promise<void> {
  return apiFetch<void>(`/user-model/goals/${encodeURIComponent(goalId)}`, { method: 'DELETE' })
}

export function fetchTasks(status: 'active' | 'completed' | null = 'active'): Promise<TaskItem[]> {
  const query = status ? `?status=${status}` : '?status='
  return apiFetch<TaskItem[]>(`/modules/tasks${query}`)
}

export function createTask(payload: CreateTaskRequest): Promise<TaskItem> {
  return apiFetch<TaskItem>('/modules/tasks', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function updateTask(taskId: string, payload: Partial<CreateTaskRequest>): Promise<TaskItem> {
  return apiFetch<TaskItem>(`/modules/tasks/${taskId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export function completeTask(taskId: string): Promise<TaskItem> {
  return apiFetch<TaskItem>(`/modules/tasks/${taskId}/complete`, { method: 'POST' })
}

export function revertTaskRewrite(taskId: string): Promise<TaskItem> {
  return apiFetch<TaskItem>(`/modules/tasks/${taskId}/revert-rewrite`, { method: 'POST' })
}

export function deleteTask(taskId: string): Promise<void> {
  return apiFetch<void>(`/modules/tasks/${taskId}`, { method: 'DELETE' })
}

export function fetchRoutineState(date: string): Promise<RoutineState> {
  return apiFetch<RoutineState>(`/modules/routine?date=${encodeURIComponent(date)}`)
}

export function createRoutineItem(payload: CreateRoutineRequest): Promise<RoutineItem> {
  return apiFetch<RoutineItem>('/modules/routine', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function updateRoutineItem(
  routineId: string,
  payload: Partial<CreateRoutineRequest>,
): Promise<RoutineItem> {
  return apiFetch<RoutineItem>(`/modules/routine/${routineId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export function completeRoutineItem(routineId: string, date: string): Promise<RoutineItem> {
  return apiFetch<RoutineItem>(`/modules/routine/${routineId}/complete`, {
    method: 'POST',
    body: JSON.stringify({ date }),
  })
}

export function uncompleteRoutineItem(routineId: string, date: string): Promise<RoutineItem> {
  return apiFetch<RoutineItem>(`/modules/routine/${routineId}/complete?date=${encodeURIComponent(date)}`, {
    method: 'DELETE',
  })
}

export function archiveRoutineItem(routineId: string): Promise<RoutineItem> {
  return apiFetch<RoutineItem>(`/modules/routine/${routineId}/archive`, { method: 'POST' })
}

export function fetchTaskPrioritySuggestion(): Promise<TaskPrioritySuggestionState> {
  return apiFetch<TaskPrioritySuggestionState>('/modules/tasks/priority-suggestion')
}

export function generateTaskPrioritySuggestion(): Promise<TaskPrioritySuggestionState> {
  return apiFetch<TaskPrioritySuggestionState>('/modules/tasks/priority-suggestion', { method: 'POST' })
}

export function updateTaskPrioritySuggestion(
  suggestionId: string,
  payload: { sort_enabled?: boolean; panel_visible?: boolean },
): Promise<TaskPrioritySuggestionState> {
  return apiFetch<TaskPrioritySuggestionState>(`/modules/tasks/priority-suggestion/${suggestionId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export function fetchPlans(status: LifecycleStatus | null = 'active'): Promise<PlanItem[]> {
  const query = status ? `?status=${status}` : '?status='
  return apiFetch<PlanItem[]>(`/modules/plans${query}`)
}

export function createPlan(payload: CreatePlanRequest): Promise<PlanItem> {
  return apiFetch<PlanItem>('/modules/plans', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function parsePlanText(rawText: string): Promise<ParsedPlanDraft> {
  return apiFetch<ParsedPlanDraft>('/modules/plans/parse', {
    method: 'POST',
    body: JSON.stringify({ raw_text: rawText }),
  })
}

export function addPlanStep(planId: string, payload: { title: string; description?: string }): Promise<PlanItem> {
  return apiFetch<PlanItem>(`/modules/plans/${planId}/steps`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function completePlanStep(planId: string, stepId: string): Promise<PlanItem> {
  return apiFetch<PlanItem>(`/modules/plans/${planId}/steps/${stepId}/complete`, { method: 'POST' })
}

export function completePlan(planId: string): Promise<PlanItem> {
  return apiFetch<PlanItem>(`/modules/plans/${planId}/complete`, { method: 'POST' })
}

export function archivePlan(planId: string): Promise<PlanItem> {
  return apiFetch<PlanItem>(`/modules/plans/${planId}/archive`, { method: 'POST' })
}

export function deletePlan(planId: string): Promise<void> {
  return apiFetch<void>(`/modules/plans/${planId}`, { method: 'DELETE' })
}

export function fetchDocuments(): Promise<DocumentItem[]> {
  return apiFetch<DocumentItem[]>('/modules/documents')
}

export function createDocument(payload: CreateDocumentRequest): Promise<DocumentItem> {
  return apiFetch<DocumentItem>('/modules/documents', {
    method: 'POST',
    body: JSON.stringify({ mime_type: 'text/plain', ...payload }),
  })
}

export function uploadDocument(file: File): Promise<DocumentItem> {
  const form = new FormData()
  form.append('file', file)
  return apiFetch<DocumentItem>('/modules/documents/upload', {
    method: 'POST',
    body: form,
  })
}

export function renameDocument(documentId: string, uniqueName: string): Promise<DocumentItem> {
  return apiFetch<DocumentItem>(`/modules/documents/${documentId}/unique-name`, {
    method: 'PATCH',
    body: JSON.stringify({ unique_name: uniqueName }),
  })
}

export function updateDocumentAnnotation(
  documentId: string,
  payload: { category_tag?: string; connection_summary?: string },
): Promise<DocumentItem> {
  return apiFetch<DocumentItem>(`/modules/documents/${documentId}/annotation`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export function respondToChat(payload: {
  session_id: string
  mode: ChatMode
  message: string
}): Promise<ChatResponse> {
  return apiFetch<ChatResponse>('/chat/respond', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export interface StreamChatHandlers {
  onStage?: (stage: string) => void
  onAnswerDelta?: (delta: string) => void
  onDone?: (suggestions: CaptureProposalPreview[]) => void
}

async function consumeSseStream(
  response: Response,
  handlers: StreamChatHandlers,
): Promise<void> {
  if (!response.body) {
    throw new Error('Streaming response had no body')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const parts = buffer.split('\n\n')
    buffer = parts.pop() ?? ''
    for (const part of parts) {
      for (const line of part.split('\n')) {
        if (!line.startsWith('data:')) continue
        const event = JSON.parse(line.slice(5).trim()) as {
          stage?: string
          delta?: string
          suggestions?: CaptureProposalPreview[]
        }
        if (event.stage === 'answer' && event.delta) {
          handlers.onAnswerDelta?.(event.delta)
        } else if (event.stage === 'done') {
          handlers.onDone?.(event.suggestions ?? [])
        } else if (event.stage) {
          handlers.onStage?.(event.stage)
        }
      }
    }
  }
}

export async function streamChat(
  payload: { session_id: string; mode: ChatMode; message: string },
  handlers: StreamChatHandlers,
): Promise<void> {
  let lastError = 'Network request failed'

  for (const base of API_BASES) {
    const url = `${base}/chat/respond/stream`
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!response.ok) {
        let detail = `${url}: ${response.status} ${response.statusText}`
        try {
          const body = await response.json()
          const bodyDetail =
            typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body)
          detail = `${url}: ${bodyDetail}`
        } catch {
          // Keep status text fallback.
        }
        lastError = detail
        if (response.status === 404 || response.status >= 500) continue
        throw new Error(detail)
      }
      await consumeSseStream(response, handlers)
      return
    } catch (err) {
      lastError = err instanceof Error ? err.message : `${url}: request failed`
      continue
    }
  }

  const fallback = await respondToChat(payload)
  handlers.onAnswerDelta?.(fallback.answer)
  handlers.onDone?.(fallback.suggestions)
}

export function confirmCaptureProposal(proposalId: string): Promise<ConfirmCaptureProposalResponse> {
  return apiFetch<ConfirmCaptureProposalResponse>('/chat/capture-proposals/confirm', {
    method: 'POST',
    body: JSON.stringify({ proposal_id: proposalId }),
  })
}

export function fetchChatSessions(): Promise<ChatSessionItem[]> {
  return apiFetch<ChatSessionItem[]>('/chat/sessions')
}

export function fetchChatMessages(sessionId: string): Promise<ChatMessageItem[]> {
  return apiFetch<ChatMessageItem[]>(`/chat/sessions/${encodeURIComponent(sessionId)}/messages`)
}

export function renameChatSession(sessionId: string, title: string): Promise<ChatSessionItem> {
  return apiFetch<ChatSessionItem>(`/chat/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'PATCH',
    body: JSON.stringify({ title }),
  })
}

export function deleteChatSession(sessionId: string): Promise<void> {
  return apiFetch<void>(`/chat/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'DELETE',
  })
}

export function fetchCuriousOnboarding(): Promise<CuriousOnboardingState> {
  return apiFetch<CuriousOnboardingState>('/modules/curious/onboarding')
}

export function fetchCuriousState(): Promise<CuriousPageState> {
  return apiFetch<CuriousPageState>('/modules/curious/state')
}

export function answerCuriousPendingQuestion(payload: {
  question_life_item_id?: string | null
  session_id?: string | null
  question_id: string
  option_id: string
}): Promise<CuriousPageState> {
  return apiFetch<CuriousPageState>('/modules/curious/questions/answer', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function weavePendingCuriousUpdates(): Promise<CuriousWeaveResult> {
  return apiFetch<CuriousWeaveResult>('/modules/curious/weave-pending', { method: 'POST' })
}

export function sendCuriousWeaveBeacon(): boolean {
  const path = '/api/modules/curious/weave-pending'
  if (typeof navigator !== 'undefined' && typeof navigator.sendBeacon === 'function') {
    return navigator.sendBeacon(path, new Blob(['{}'], { type: 'application/json' }))
  }
  if (typeof fetch !== 'undefined') {
    void fetch(path, { method: 'POST', keepalive: true })
    return true
  }
  return false
}

export function answerCuriousQuestion(payload: {
  session_id: string
  question_id: string
  option_id: string
}): Promise<CuriousOnboardingState> {
  return apiFetch<CuriousOnboardingState>('/modules/curious/onboarding/answers', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function completeCuriousOnboarding(sessionId: string): Promise<CuriousCompletion> {
  return apiFetch<CuriousCompletion>('/modules/curious/onboarding/complete', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId }),
  })
}

export function fetchCompanionState(): Promise<CompanionState> {
  return apiFetch<CompanionState>('/modules/curious/companion/state')
}

export function sendCompanionMessage(message: string): Promise<CompanionMessageResponse> {
  return apiFetch<CompanionMessageResponse>('/modules/curious/companion/message', {
    method: 'POST',
    body: JSON.stringify({ message }),
  })
}

export function askCompanionQuestion(): Promise<CompanionMessageResponse> {
  return apiFetch<CompanionMessageResponse>('/modules/curious/companion/ask', { method: 'POST' })
}

export function skipCompanionQuestion(bucketKey?: string | null): Promise<CompanionMessageResponse> {
  return apiFetch<CompanionMessageResponse>('/modules/curious/companion/skip', {
    method: 'POST',
    body: JSON.stringify({ bucket_key: bucketKey ?? null }),
  })
}

export function endCompanionSession(): Promise<CuriousWeaveResult> {
  return apiFetch<CuriousWeaveResult>('/modules/curious/companion/end', { method: 'POST' })
}

export function sendCompanionEndBeacon(): boolean {
  const path = '/api/modules/curious/companion/end'
  if (typeof navigator !== 'undefined' && typeof navigator.sendBeacon === 'function') {
    return navigator.sendBeacon(path, new Blob(['{}'], { type: 'application/json' }))
  }
  if (typeof fetch !== 'undefined') {
    void fetch(path, { method: 'POST', keepalive: true })
    return true
  }
  return false
}

export function fetchStoryBuckets(): Promise<StoryBucketItem[]> {
  return apiFetch<StoryBucketItem[]>('/user-model/buckets')
}

export function updateStoryBucket(
  bucketId: string,
  payload: { display_name?: string; description?: string; content: string },
): Promise<StoryBucketItem> {
  return apiFetch<StoryBucketItem>(`/user-model/buckets/${bucketId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}
