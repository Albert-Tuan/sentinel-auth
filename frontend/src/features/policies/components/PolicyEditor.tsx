/**
 * S-32 — Policy Editor.
 *
 * The editor writes the whole policy back with `PUT /policies/{id}`.
 * Three backend contracts shape it:
 *
 *   1. **Optimistic concurrency.** The write MUST carry
 *      `expected_updated_at` — the `updated_at` the client last read. The
 *      backend answers 409 "Policy was modified by someone else" when the
 *      token does not match, and 409 "Policy is immutable" when the
 *      policy has been active. The token is kept as the raw STRING: a
 *      `Date` round-trip loses the microsecond precision the backend
 *      compares with, which would produce spurious conflicts.
 *
 *   2. **The server owns `is_active`, `created_by` and the timestamps.**
 *      The payload never carries them.
 *
 *   3. **The server validates the rules.** The client mirrors those
 *      validators in `policyValidation.ts` so the operator sees the
 *      problem before the request — but the SERVER decides, and its
 *      answer is always shown verbatim.
 *
 * The editor is read-only when the policy is frozen. The screen then
 * shows the values but never sends them, because the backend would
 * answer 409 anyway.
 */

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { Badge } from '@/shared/components/Badge'
import { Button } from '@/shared/components/Button'
import { ErrorState } from '@/shared/components/ErrorState'

import { updatePolicy } from '@/lib/api/policies.api'
import { toApiError } from '@/lib/errors'
import type { PolicyDetail, PolicyRule } from '@/types/api'

import {
  ALLOWED_FEATURE_FIELDS,
  ALLOWED_OPERATORS,
  isRangeOperator,
  parseRuleValue,
  validateRule,
  validateThresholds,
  validateWeights,
} from '@/features/policies/policyValidation'

export interface PolicyEditorProps {
  policy: PolicyDetail
  /** The editor renders but does not submit. */
  readOnly?: boolean
}

/**
 * The editor's own copy of a rule.
 *
 * The `value` is held as TEXT, because the operator types it: a range is
 * "0.4, 0.8", a list is "a, b, c". It is parsed to the JSON the backend
 * expects only when the rule is validated and submitted.
 */
interface DraftRule {
  key: string
  name: string
  field: string
  operator: string
  value: string
  weight: string
  score: string
  enabled: boolean
}

/**
 * Turn a policy rule into a draft.
 *
 * A rule whose value is a list is joined with ", " so it round-trips
 * through the text field unchanged.
 */
function toDraftRule(rule: PolicyRule, index: number): DraftRule {
  const value = Array.isArray(rule.value)
    ? rule.value.map((part) => String(part)).join(', ')
    : String(rule.value ?? '')

  return {
    key: `${index}-${rule.name}`,
    name: rule.name,
    field: rule.field,
    operator: rule.operator,
    value,
    weight: String(rule.weight),
    score: String(rule.score),
    enabled: rule.enabled,
  }
}

/**
 * Parse a draft rule into the JSON the backend expects.
 *
 * @returns the rule, or `null` when the value cannot be parsed.
 */
function fromDraftRule(draft: DraftRule): PolicyRule | null {
  const value = parseRuleValue(draft.value, draft.operator)
  if (value === null) return null

  return {
    name: draft.name.trim(),
    field: draft.field,
    operator: draft.operator,
    value,
    weight: Number(draft.weight),
    score: Number(draft.score),
    enabled: draft.enabled,
    description: null,
  }
}

export function PolicyEditor({ policy, readOnly = false }: PolicyEditorProps) {
  const queryClient = useQueryClient()

  const [name, setName] = useState(policy.name ?? '')
  const [description, setDescription] = useState(policy.description ?? '')
  const [rules, setRules] = useState<DraftRule[]>(() =>
    policy.rules.map(toDraftRule),
  )
  const [ruleWeight, setRuleWeight] = useState(
    String(policy.config?.weights?.rule ?? 0.4),
  )
  const [mlWeight, setMlWeight] = useState(
    String(policy.config?.weights?.ml ?? 0.6),
  )
  const [low, setLow] = useState(String(policy.config?.thresholds?.low ?? 0.25))
  const [medium, setMedium] = useState(
    String(policy.config?.thresholds?.medium ?? 0.5),
  )
  const [high, setHigh] = useState(String(policy.config?.thresholds?.high ?? 0.75))

  const saveMutation = useMutation({
    mutationFn: () => {
      const parsedRules = rules.map(fromDraftRule)
      if (parsedRules.some((rule) => rule === null)) {
        // The validation below already reported the broken rule; the
        // request is never sent with a hole in it.
        throw new Error('invalid rule value')
      }

      return updatePolicy(policy.id, {
        name: name.trim() || undefined,
        description: description.trim() || undefined,
        rules: parsedRules as PolicyRule[],
        config: {
          weights: { rule: Number(ruleWeight), ml: Number(mlWeight) },
          thresholds: {
            low: Number(low),
            medium: Number(medium),
            high: Number(high),
          },
        },
        // The optimistic-concurrency token: the raw string, unmodified.
        expected_updated_at: policy.updated_at,
      })
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['policies'] })
    },
  })

  /** The problems of every rule, computed on the current draft. */
  const ruleProblems = rules.map((draft) => {
    const parsed = fromDraftRule(draft)
    if (parsed === null) {
      return ['Giá trị không hợp lệ']
    }
    return validateRule(parsed)
  })

  const weightProblems = validateWeights(Number(ruleWeight), Number(mlWeight))
  const thresholdProblems = validateThresholds(
    Number(low),
    Number(medium),
    Number(high),
  )

  const duplicateNames = findDuplicateNames(rules)
  const hasProblems =
    ruleProblems.some((problems) => problems.length > 0) ||
    weightProblems.length > 0 ||
    thresholdProblems.length > 0 ||
    duplicateNames.length > 0

  function updateRule(key: string, patch: Partial<DraftRule>) {
    setRules((current) =>
      current.map((draft) => (draft.key === key ? { ...draft, ...patch } : draft)),
    )
  }

  function addRule() {
    setRules((current) => [
      ...current,
      {
        key: `new-${current.length}-${Date.now()}`,
        name: '',
        field: ALLOWED_FEATURE_FIELDS[0],
        operator: '>',
        value: '0',
        weight: '0.5',
        score: '0.5',
        enabled: true,
      },
    ])
  }

  function removeRule(key: string) {
    setRules((current) => current.filter((draft) => draft.key !== key))
  }

  return (
    <section className="flex flex-col gap-4" aria-labelledby="policy-editor-heading">
      <div className="flex items-center justify-between border-b border-border pb-2">
        <h2 id="policy-editor-heading" className="heading-ops text-text">
          Cấu hình chính sách
        </h2>
        <span className="telemetry text-xs text-text-muted">
          ID: {policy.id.slice(0, 8).toUpperCase()}
        </span>
      </div>

      {readOnly && (
        <div
          role="status"
          className="border border-l-4 border-border border-l-warning bg-surface-raised p-3 text-sm text-text-muted"
        >
          Chế độ chỉ đọc — chính sách đã từng được kích hoạt nên không thể sửa.
        </div>
      )}

      {/* --- General info ------------------------------------------------ */}
      <div className="flex flex-col gap-4 border border-border bg-surface-raised p-4">
        <h3 className="heading-ops text-text">THÔNG TIN CHUNG</h3>
        <div className="grid gap-4 md:grid-cols-2">
          <div className="flex flex-col gap-1">
            <label htmlFor="policy-name" className="label-ops text-text-muted">
              Tên chính sách
            </label>
            <input
              id="policy-name"
              value={name}
              disabled={readOnly}
              onChange={(event) => setName(event.target.value)}
              className="telemetry border border-border bg-surface-sunken px-3 py-2 text-sm text-text outline-none focus:border-primary disabled:text-degraded"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label
              htmlFor="policy-description"
              className="label-ops text-text-muted"
            >
              Mô tả cấu hình
            </label>
            <input
              id="policy-description"
              value={description}
              disabled={readOnly}
              onChange={(event) => setDescription(event.target.value)}
              className="telemetry border border-border bg-surface-sunken px-3 py-2 text-sm text-text outline-none focus:border-primary disabled:text-degraded"
            />
          </div>
        </div>
      </div>

      {/* --- Rules -------------------------------------------------------- */}
      <div className="flex flex-col gap-3 border border-border bg-surface-raised p-4">
        <div className="flex items-center justify-between border-b border-border pb-2">
          <h3 className="heading-ops text-text">QUY TẮC PHÁT HIỆN</h3>
          <Badge tone="info">{rules.length} QUY TẮC</Badge>
        </div>

        {rules.length === 0 && (
          <p className="text-sm text-degraded">
            Chính sách chưa có quy tắc nào. Backend yêu cầu ít nhất một quy
            tắc.
          </p>
        )}

        {rules.map((draft, index) => (
          <RuleCard
            key={draft.key}
            draft={draft}
            index={index}
            problems={ruleProblems[index] ?? []}
            duplicate={duplicateNames.includes(draft.name.trim())}
            readOnly={readOnly}
            onChange={(patch) => updateRule(draft.key, patch)}
            onRemove={() => removeRule(draft.key)}
          />
        ))}

        {!readOnly && (
          <Button variant="secondary" onClick={addRule} className="self-start">
            Thêm quy tắc
          </Button>
        )}
      </div>

      {/* --- Config ------------------------------------------------------- */}
      <div className="flex flex-col gap-4 border border-border bg-surface-raised p-4">
        <h3 className="heading-ops text-text">
          CẤU HÌNH TRỌNG SỐ & NGƯỠNG RỦI RO
        </h3>

        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <span className="label-ops text-text-muted">
              Trọng số quyết định (Rule Engine vs Machine Learning)
            </span>
            <span className="telemetry text-xs text-primary">
              Rule: {ruleWeight} | ML: {mlWeight}
            </span>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <NumberField
              id="policy-weight-rule"
              label="Trọng số Heuristic Rules"
              value={ruleWeight}
              disabled={readOnly}
              onChange={setRuleWeight}
            />
            <NumberField
              id="policy-weight-ml"
              label="Trọng số Mô hình ML"
              value={mlWeight}
              disabled={readOnly}
              onChange={setMlWeight}
            />
          </div>
          {weightProblems.length > 0 && (
            <p role="alert" className="text-xs text-danger">
              {weightProblems.join('; ')}
            </p>
          )}
        </div>

        <div className="flex flex-col gap-2 border-t border-border pt-3">
          <div className="flex items-center justify-between">
            <span className="label-ops text-text-muted">
              Ngưỡng phân loại rủi ro (Risk Tiers)
            </span>
            <span className="telemetry text-xs text-text-muted">
              CRITICAL: &gt;= {high}
            </span>
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            <NumberField
              id="policy-threshold-low"
              label="Mức thấp (LOW)"
              value={low}
              disabled={readOnly}
              onChange={setLow}
            />
            <NumberField
              id="policy-threshold-medium"
              label="Mức trung bình (MEDIUM)"
              value={medium}
              disabled={readOnly}
              onChange={setMedium}
            />
            <NumberField
              id="policy-threshold-high"
              label="Mức cao (HIGH)"
              value={high}
              disabled={readOnly}
              onChange={setHigh}
            />
          </div>
          {thresholdProblems.length > 0 && (
            <p role="alert" className="text-xs text-danger">
              {thresholdProblems.join('; ')}
            </p>
          )}
        </div>
      </div>

      {/* --- Save --------------------------------------------------------- */}
      {!readOnly && (
        <div className="sticky bottom-4 z-30 flex flex-wrap items-center justify-between gap-4 border border-border bg-surface-raised p-4">
          <div className="flex flex-col">
            <span className="label-ops text-text-muted">Trạng thái phát hành</span>
            <span className="telemetry text-xs text-warning">
              BẢN NHÁP — CHƯA KÍCH HOẠT
            </span>
          </div>
          <Button
            onClick={() => saveMutation.mutate()}
            loading={saveMutation.isPending}
            disabled={hasProblems || rules.length === 0}
          >
            Lưu thay đổi
          </Button>
        </div>
      )}

      {saveMutation.isError && (
        <ErrorState
          title="Không thể lưu chính sách"
          message={toApiError(saveMutation.error).userMessage}
        />
      )}
    </section>
  )
}

/**
 * One rule, as an editable card.
 *
 * The problems are shown per field so the operator knows which knob is
 * wrong, not just that something is.
 */
function RuleCard({
  draft,
  index,
  problems,
  duplicate,
  readOnly,
  onChange,
  onRemove,
}: {
  draft: DraftRule
  index: number
  problems: string[]
  duplicate: boolean
  readOnly: boolean
  onChange: (patch: Partial<DraftRule>) => void
  onRemove: () => void
}) {
  const valueHint = isRangeOperator(draft.operator)
    ? 'Định dạng: min, max (ví dụ 0.4, 0.8)'
    : draft.operator === 'in'
      ? 'Định dạng: a, b, c'
      : 'Một giá trị đơn'

  return (
    <div
      className={`flex flex-col gap-3 border bg-surface-sunken p-3 ${
        problems.length > 0 || duplicate ? 'border-danger' : 'border-border'
      }`}
    >
      <div className="flex items-center justify-between border-b border-border/60 pb-2">
        <div className="flex items-center gap-2">
          <span className="telemetry text-xs font-bold text-text">
            [RULE {String(index + 1).padStart(2, '0')}]
          </span>
          {duplicate && (
            <span className="label-ops text-danger">
              TRÙNG TÊN QUY TẮC
            </span>
          )}
          {problems.length > 0 && (
            <span className="label-ops text-danger">LỖI THẨM ĐỊNH</span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <label
            htmlFor={`rule-enabled-${draft.key}`}
            className="label-ops text-text-muted"
          >
            <input
              id={`rule-enabled-${draft.key}`}
              type="checkbox"
              checked={draft.enabled}
              disabled={readOnly}
              onChange={(event) => onChange({ enabled: event.target.checked })}
              className="mr-2 accent-primary"
            />
            Kích hoạt
          </label>
          {!readOnly && (
            <Button variant="ghost" onClick={onRemove}>
              Xoá
            </Button>
          )}
        </div>
      </div>

      <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
        <Field label="Tên quy tắc" id={`rule-name-${draft.key}`}>
          <input
            id={`rule-name-${draft.key}`}
            value={draft.name}
            disabled={readOnly}
            onChange={(event) => onChange({ name: event.target.value })}
            className="telemetry w-full border border-border bg-surface-raised px-2.5 py-2 text-sm text-text outline-none focus:border-primary disabled:text-degraded"
          />
        </Field>

        <Field label="Trường dữ liệu" id={`rule-field-${draft.key}`}>
          <select
            id={`rule-field-${draft.key}`}
            value={draft.field}
            disabled={readOnly}
            onChange={(event) => onChange({ field: event.target.value })}
            className="telemetry w-full border border-border bg-surface-raised px-2.5 py-2 text-sm text-text outline-none focus:border-primary disabled:text-degraded"
          >
            {ALLOWED_FEATURE_FIELDS.map((field) => (
              <option key={field} value={field}>
                {field}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Toán tử" id={`rule-operator-${draft.key}`}>
          <select
            id={`rule-operator-${draft.key}`}
            value={draft.operator}
            disabled={readOnly}
            onChange={(event) => onChange({ operator: event.target.value })}
            className="telemetry w-full border border-border bg-surface-raised px-2.5 py-2 text-sm text-text outline-none focus:border-primary disabled:text-degraded"
          >
            {ALLOWED_OPERATORS.map((operator) => (
              <option key={operator} value={operator}>
                {operator}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Giá trị" id={`rule-value-${draft.key}`} hint={valueHint}>
          <input
            id={`rule-value-${draft.key}`}
            value={draft.value}
            disabled={readOnly}
            onChange={(event) => onChange({ value: event.target.value })}
            className="telemetry w-full border border-border bg-surface-raised px-2.5 py-2 text-sm text-text outline-none focus:border-primary disabled:text-degraded"
          />
        </Field>

        <Field label="Trọng số [0.0-1.0]" id={`rule-weight-${draft.key}`}>
          <input
            id={`rule-weight-${draft.key}`}
            value={draft.weight}
            disabled={readOnly}
            onChange={(event) => onChange({ weight: event.target.value })}
            className="telemetry w-full border border-border bg-surface-raised px-2.5 py-2 text-sm text-text outline-none focus:border-primary disabled:text-degraded"
          />
        </Field>

        <Field label="Điểm [0.0-1.0]" id={`rule-score-${draft.key}`}>
          <input
            id={`rule-score-${draft.key}`}
            value={draft.score}
            disabled={readOnly}
            onChange={(event) => onChange({ score: event.target.value })}
            className="telemetry w-full border border-border bg-surface-raised px-2.5 py-2 text-sm text-text outline-none focus:border-primary disabled:text-degraded"
          />
        </Field>
      </div>

      {problems.length > 0 && (
        <ul role="alert" className="flex flex-col gap-1 text-xs text-danger">
          {problems.map((problem) => (
            <li key={problem}>• {problem}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

/**
 * A labelled control.
 */
function Field({
  label,
  id,
  hint,
  children,
}: {
  label: string
  id: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="label-ops text-text-muted">
        {label}
      </label>
      {children}
      {hint && <span className="text-[10px] text-degraded">{hint}</span>}
    </div>
  )
}

/**
 * A numeric field.
 *
 * The value is held as TEXT so the operator can type a partial number
 * ("0." ) without the field fighting them; it is parsed when the payload
 * is built.
 */
function NumberField({
  id,
  label,
  value,
  disabled,
  onChange,
}: {
  id: string
  label: string
  value: string
  disabled?: boolean
  onChange: (value: string) => void
}) {
  return (
    <Field label={label} id={id}>
      <input
        id={id}
        inputMode="decimal"
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        className="telemetry w-full border border-border bg-surface-sunken px-3 py-2 text-sm text-text outline-none focus:border-primary disabled:text-degraded"
      />
    </Field>
  )
}

/**
 * The names that appear more than once.
 *
 * The backend rejects a duplicate rule name with a 400, so the editor
 * reports it before the request.
 */
function findDuplicateNames(rules: DraftRule[]): string[] {
  const seen = new Map<string, number>()
  for (const rule of rules) {
    const name = rule.name.trim()
    if (!name) continue
    seen.set(name, (seen.get(name) ?? 0) + 1)
  }
  return [...seen.entries()]
    .filter(([, count]) => count > 1)
    .map(([name]) => name)
}
