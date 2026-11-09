import {render,screen} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {describe,it,expect} from 'vitest'
import {
  TransactionNetwork3D,
  classifyFindingState,
  evaluateEntityRisk
} from './visualizations'

describe('Forensic Network 3D & Risk Classification', () => {
  it('correctly classifies finding states according to specification', () => {
    // INCONSISTENT / IMPOSSIBLE -> Suspicious / Critical
    expect(classifyFindingState('INCONSISTENT')).toEqual({ risk: 'critical', label: 'Suspicious / Critical', suspicious: true })
    expect(classifyFindingState('IMPOSSIBLE')).toEqual({ risk: 'critical', label: 'Suspicious / Critical', suspicious: true })

    // GAP / UNAVAILABLE / UNVERIFIED -> Evidence gap
    expect(classifyFindingState('GAP')).toEqual({ risk: 'serious', label: 'Evidence gap', suspicious: false })
    expect(classifyFindingState('UNAVAILABLE')).toEqual({ risk: 'serious', label: 'Evidence gap', suspicious: false })
    expect(classifyFindingState('UNVERIFIED')).toEqual({ risk: 'serious', label: 'Evidence gap', suspicious: false })

    // REVIEW -> Needs review
    expect(classifyFindingState('REVIEW')).toEqual({ risk: 'warning', label: 'Needs review', suspicious: false })

    // DISCLOSED_RELATED_PARTY -> Context
    expect(classifyFindingState('DISCLOSED_RELATED_PARTY')).toEqual({ risk: 'info', label: 'Context', suspicious: false })

    // Normal / unspecified
    expect(classifyFindingState(undefined)).toEqual({ risk: 'normal', label: 'Normal', suspicious: false })
  })

  it('evaluates entity risk without treating evidence gaps or disclosed parties as suspicious', () => {
    // Evidence gap alone
    expect(evaluateEntityRisk([{ state: 'GAP' }])).toEqual({ risk: 'serious', suspicious: false })

    // Disclosed related party alone
    expect(evaluateEntityRisk([{ state: 'DISCLOSED_RELATED_PARTY' }])).toEqual({ risk: 'info', suspicious: false })

    // Needs review alone
    expect(evaluateEntityRisk([{ state: 'REVIEW' }])).toEqual({ risk: 'warning', suspicious: false })

    // Inconsistent / Impossible
    expect(evaluateEntityRisk([{ state: 'INCONSISTENT' }])).toEqual({ risk: 'critical', suspicious: true })
    expect(evaluateEntityRisk([{ state: 'GAP' }, { state: 'INCONSISTENT' }])).toEqual({ risk: 'critical', suspicious: true })
  })

  it('renders all transactions and entities when Suspicious Only is OFF', () => {
    const invoices = [
      { invoice_id: 'INV-1', bill_no: 'INV-001', customer_id: 'CUST-1', gross_cents: 100000 },
      { invoice_id: 'INV-2', bill_no: 'INV-002', customer_id: 'CUST-2', gross_cents: 200000 }
    ]
    const customers = [
      { customer_id: 'CUST-1', name: 'Alpha Corp' },
      { customer_id: 'CUST-2', name: 'Beta Ltd' }
    ]

    render(
      <TransactionNetwork3D
        invoices={invoices}
        customers={customers}
        findings={[]}
      />
    )

    // Check counters: 2 Invoices, 3 Entities (2 customers + Reporting Entity), 4 Links (2 corp->cust, 2 cust->inv)
    expect(screen.getByText('2 Invoices')).toBeInTheDocument()
    expect(screen.getByText('3 Entities')).toBeInTheDocument()
    expect(screen.getByText('4 Links')).toBeInTheDocument()
  })

  it('updates counters and isolates suspicious items when Suspicious Only is toggled ON', async () => {
    const invoices = [
      { invoice_id: 'INV-1', bill_no: 'INV-001', customer_id: 'CUST-1', gross_cents: 100000 },
      { invoice_id: 'INV-CRIT', bill_no: 'INV-002', customer_id: 'CUST-2', gross_cents: 200000 }
    ]
    const customers = [
      { customer_id: 'CUST-1', name: 'Alpha Corp' },
      { customer_id: 'CUST-2', name: 'Beta Ltd' }
    ]
    const findings = [
      { finding_id: 'F-1', object_ref: 'INV-CRIT', state: 'INCONSISTENT', reason: 'Mismatch in dispatch vs sales' }
    ]

    render(
      <TransactionNetwork3D
        invoices={invoices}
        customers={customers}
        findings={findings}
      />
    )

    const suspiciousBtn = screen.getByRole('button', { name: /Suspicious Only/i })
    await userEvent.click(suspiciousBtn)

    // In Suspicious Only mode: visibleInvoices = 1 (INV-CRIT), total = 2. visibleEntities = 2 (CUST-2 + Reporting Entity), total = 3
    expect(screen.getByText('1 / 2 Invoices')).toBeInTheDocument()
    expect(screen.getByText('2 / 3 Entities')).toBeInTheDocument()
  })

  it('displays empty state when Suspicious Only is ON and no suspicious records exist', async () => {
    const invoices = [
      { invoice_id: 'INV-1', bill_no: 'INV-001', customer_id: 'CUST-1', gross_cents: 100000 }
    ]
    const customers = [
      { customer_id: 'CUST-1', name: 'Alpha Corp' }
    ]
    // Only normal findings / evidence gaps / review
    const findings = [
      { finding_id: 'F-GAP', object_ref: 'INV-1', state: 'GAP', reason: 'Missing dispatch document' }
    ]

    render(
      <TransactionNetwork3D
        invoices={invoices}
        customers={customers}
        findings={findings}
      />
    )

    const suspiciousBtn = screen.getByRole('button', { name: /Suspicious Only/i })
    await userEvent.click(suspiciousBtn)

    expect(screen.getByText('No suspicious relationships identified for this audit dataset.')).toBeInTheDocument()
  })

  it('handles credit notes and connects them to original invoices without false suspicion', () => {
    const invoices = [
      { invoice_id: 'INV-100', bill_no: 'INV-100', customer_id: 'CUST-1', gross_cents: 50000 },
      { credit_note_id: 'CR-100', invoice_id: 'INV-100', bill_no: 'CR-100', customer_id: 'CUST-1', amount_cents: 50000, reason: 'Legitimate goods return' }
    ]
    const customers = [
      { customer_id: 'CUST-1', name: 'Alpha Corp' }
    ]

    render(
      <TransactionNetwork3D
        invoices={invoices}
        customers={customers}
        findings={[]}
      />
    )

    expect(screen.getByText('2 Invoices')).toBeInTheDocument()
    // Links: corp->cust (1), cust->inv (1), cr->inv reversal (1) = 3 Links
    expect(screen.getByText('3 Links')).toBeInTheDocument()
  })

  it('handles T02 circular cycles accurately', () => {
    const invoices: any[] = []
    const customers = [
      { customer_id: 'CUST-A', name: 'Entity A' },
      { customer_id: 'CUST-B', name: 'Entity B' },
      { customer_id: 'CUST-C', name: 'Entity C' }
    ]
    const findings = [
      {
        finding_id: 'F-T02-CYCLE',
        test_id: 'T02',
        state: 'REVIEW',
        cycle_nodes: ['CUST-A', 'CUST-B', 'CUST-C'],
        cycle_path: ['CUST-A', 'CUST-B', 'CUST-C', 'CUST-A'],
        reason: 'A directed cycle exists in the synthetic counterparty graph'
      }
    ]

    render(
      <TransactionNetwork3D
        invoices={invoices}
        customers={customers}
        findings={findings}
      />
    )

    // Links: corp->A, corp->B, corp->C (3) + 3 cycle edges (A->B, B->C, C->A) = 6 Links
    expect(screen.getByText('6 Links')).toBeInTheDocument()
  })
})
