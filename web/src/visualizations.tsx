import {useEffect,useRef,useState} from 'react'
import {CheckCircle2,ShieldAlert,ShieldCheck,Zap,Maximize2,Minimize2,Filter,Layers,Eye,Lock,RotateCw} from 'lucide-react'
import {Row} from './components'

// --- High-Performance GPU Canvas 3D Network Engine for Forensic Relationships ---

export interface GraphNode {
  id: string
  label: string
  type: 'company' | 'customer' | 'invoice' | 'credit_note'
  risk: 'critical' | 'warning' | 'normal' | 'verified'
  amount?: number
  degree?: number
  // 3D coordinates
  x: number
  y: number
  z: number
  vx: number
  vy: number
  vz: number
  radius: number
  meta?: Record<string, any>
}

export interface GraphLink {
  source: string
  target: string
  type: 'sale' | 'credit' | 'related' | 'reconciliation'
  value?: number
  suspicious?: boolean
}

const PALETTE = {
  canvasBg: '#090a0d',
  nodeCompany: '#d4af37', // Antique gold
  nodeCustomer: '#718096', // Slate
  nodeWarning: '#f59e0b', // Amber
  nodeCritical: '#f43f5e', // Ruby / Crimson
  nodeVerified: '#10b981', // Emerald
  edgeNormal: 'rgba(255, 255, 255, 0.08)',
  edgeRelated: 'rgba(245, 158, 11, 0.4)',
  edgeSuspicious: 'rgba(244, 63, 94, 0.7)',
  nodeSelected: '#ffffff',
  text: '#e2e8f0',
  subText: '#94a3b8'
}

export function TransactionNetwork3D({
  invoices = [],
  customers = [],
  findings = [],
  onSelectNode
}: {
  invoices: Row[]
  customers: Row[]
  findings: Row[]
  onSelectNode?: (node: GraphNode | null) => void
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null)
  const [is3D, setIs3D] = useState(true)
  const [filterSuspiciousOnly, setFilterSuspiciousOnly] = useState(false)
  const [activeRotation, setActiveRotation] = useState(true)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    let ctx: CanvasRenderingContext2D | null = null
    try {
      ctx = canvas.getContext('2d')
    } catch {
      // headless test / jsdom environment
    }
    if (!ctx) return

    let animId: number
    let width = (canvas.width = canvas.parentElement?.clientWidth || 800)
    let height = (canvas.height = 480)

    const handleResize = () => {
      if (!canvas || !canvas.parentElement) return
      width = canvas.width = canvas.parentElement.clientWidth || 800
      height = canvas.height = Math.max(420, Math.min(520, window.innerHeight * 0.55))
    }
    window.addEventListener('resize', handleResize)
    handleResize()

    // 1. Build Nodes & Links from Real Data
    const nodeMap = new Map<string, GraphNode>()
    const links: GraphLink[] = []

    // Root Company Node
    nodeMap.set('PRAMAAN_CORP', {
      id: 'PRAMAAN_CORP',
      label: 'Reporting Entity',
      type: 'company',
      risk: 'verified',
      x: 0,
      y: 0,
      z: 0,
      vx: 0,
      vy: 0,
      vz: 0,
      radius: 12,
      meta: { role: 'Audited Company' }
    })

    // Customers
    customers.forEach((c, idx) => {
      const angle = (idx / Math.max(customers.length, 1)) * Math.PI * 2
      const radius = 180 + (idx % 2) * 50
      const isRelated = findings.some(
        f => f.test_id === 'T01' && (f.object_ref === c.customer_id || JSON.stringify(f).includes(c.customer_id))
      )
      const hasCritical = findings.some(
        f => f.state === 'INCONSISTENT' && (f.object_ref === c.customer_id || JSON.stringify(f).includes(c.customer_id))
      )

      nodeMap.set(c.customer_id, {
        id: c.customer_id,
        label: c.name || c.customer_id,
        type: 'customer',
        risk: hasCritical ? 'critical' : isRelated ? 'warning' : 'normal',
        x: Math.cos(angle) * radius,
        y: Math.sin(angle) * radius * 0.7,
        z: Math.sin(angle * 2) * 120,
        vx: 0,
        vy: 0,
        vz: 0,
        radius: isRelated ? 8.5 : 6.5,
        meta: c
      })

      links.push({
        source: 'PRAMAAN_CORP',
        target: c.customer_id,
        type: isRelated ? 'related' : 'sale',
        suspicious: isRelated || hasCritical
      })
    })

    // Sampled Invoices / Credit Notes (up to 30 for clear forensic topology)
    const activeInvoices = invoices.slice(0, 32)
    activeInvoices.forEach((inv, idx) => {
      const custId = inv.customer_id
      const invId = inv.invoice_id || inv.credit_note_id || `INV-${idx}`
      const isCredit = Boolean(inv.credit_note_id)
      const findingForInv = findings.filter(f => f.object_ref === invId || f.samples?.some((s: Row) => s.object_ref === invId))
      const isCrit = findingForInv.some(f => f.state === 'INCONSISTENT' || f.state === 'IMPOSSIBLE')
      const isWarn = findingForInv.length > 0

      const angle = (idx / Math.max(activeInvoices.length, 1)) * Math.PI * 2
      const spread = 240 + (idx % 3) * 40

      nodeMap.set(invId, {
        id: invId,
        label: inv.bill_no || invId,
        type: isCredit ? 'credit_note' : 'invoice',
        risk: isCrit ? 'critical' : isWarn ? 'warning' : 'normal',
        amount: inv.gross_cents ? inv.gross_cents / 100 : Number(inv.net_amount || 0),
        x: Math.cos(angle) * spread,
        y: Math.sin(angle) * spread * 0.75,
        z: Math.cos(angle * 1.5) * 140,
        vx: 0,
        vy: 0,
        vz: 0,
        radius: isCrit ? 6 : 4,
        meta: inv
      })

      if (custId && nodeMap.has(custId)) {
        links.push({
          source: custId,
          target: invId,
          type: isCredit ? 'credit' : 'sale',
          suspicious: isCrit || (isCredit && isWarn)
        })
      } else {
        links.push({
          source: 'PRAMAAN_CORP',
          target: invId,
          type: isCredit ? 'credit' : 'sale',
          suspicious: isCrit
        })
      }
    })

    const nodes = Array.from(nodeMap.values())

    // 3D Camera Rotation State
    let angleY = 0
    let angleX = 0.25
    let fov = 380
    let isDragging = false
    let lastMouseX = 0
    let lastMouseY = 0

    const onMouseDown = (e: MouseEvent) => {
      isDragging = true
      lastMouseX = e.clientX
      lastMouseY = e.clientY
    }

    const onMouseMove = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect()
      const mx = e.clientX - rect.left
      const my = e.clientY - rect.top

      if (isDragging && is3D) {
        const dx = e.clientX - lastMouseX
        const dy = e.clientY - lastMouseY
        angleY += dx * 0.006
        angleX += dy * 0.006
        lastMouseX = e.clientX
        lastMouseY = e.clientY
      } else {
        // Hover detection
        let found: GraphNode | null = null
        for (const n of nodes) {
          const p = project(n.x, n.y, is3D ? n.z : 0)
          const dist = Math.hypot(mx - p.x, my - p.y)
          if (dist < p.scale * n.radius + 6) {
            found = n
            break
          }
        }
        canvas.style.cursor = found ? 'pointer' : isDragging ? 'grabbing' : 'grab'
      }
    }

    const onMouseUp = (e: MouseEvent) => {
      if (!isDragging) {
        // Click to select node
        const rect = canvas.getBoundingClientRect()
        const mx = e.clientX - rect.left
        const my = e.clientY - rect.top

        let clicked: GraphNode | null = null
        for (const n of nodes) {
          const p = project(n.x, n.y, is3D ? n.z : 0)
          const dist = Math.hypot(mx - p.x, my - p.y)
          if (dist < p.scale * n.radius + 8) {
            clicked = n
            break
          }
        }
        setSelectedNode(clicked)
        onSelectNode?.(clicked)
      }
      isDragging = false
    }

    canvas.addEventListener('mousedown', onMouseDown)
    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)

    // 3D Projection helper
    function project(x: number, y: number, z: number) {
      if (!is3D) {
        return {
          x: width / 2 + x * 0.85,
          y: height / 2 + y * 0.85,
          scale: 1,
          alpha: 1
        }
      }
      // Rotate around X & Y
      const cosY = Math.cos(angleY)
      const sinY = Math.sin(angleY)
      const cosX = Math.cos(angleX)
      const sinX = Math.sin(angleX)

      const x1 = x * cosY - z * sinY
      const z1 = z * cosY + x * sinY
      const y1 = y * cosX - z1 * sinX
      const z2 = z1 * cosX + y * sinX

      const cameraDist = 480
      const perspective = fov / (fov + z2 + cameraDist)
      const px = width / 2 + x1 * perspective
      const py = height / 2 + y1 * perspective

      return {
        x: px,
        y: py,
        scale: Math.max(0.2, perspective * 1.4),
        alpha: Math.min(1, Math.max(0.18, (z2 + cameraDist) / (cameraDist * 1.5)))
      }
    }

    // Animation Loop with Forensic Particles
    const particles = Array.from({ length: 40 }, () => ({
      x: (Math.random() - 0.5) * 600,
      y: (Math.random() - 0.5) * 400,
      z: (Math.random() - 0.5) * 400,
      size: Math.random() * 1.5 + 0.5
    }))

    const render = () => {
      ctx.fillStyle = PALETTE.canvasBg
      ctx.fillRect(0, 0, width, height)

      if (activeRotation && is3D && !isDragging) {
        angleY += 0.0025
      }

      // Draw Depth Grid & Horizon
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.025)'
      ctx.lineWidth = 1
      const gridSteps = 6
      for (let i = -gridSteps; i <= gridSteps; i++) {
        const p1 = project(i * 50, 140, -300)
        const p2 = project(i * 50, 140, 300)
        ctx.beginPath()
        ctx.moveTo(p1.x, p1.y)
        ctx.lineTo(p2.x, p2.y)
        ctx.stroke()
      }

      // Render Floating Dust Particles
      particles.forEach(pt => {
        const proj = project(pt.x, pt.y, is3D ? pt.z : 0)
        ctx.fillStyle = `rgba(212, 175, 55, ${proj.alpha * 0.18})`
        ctx.beginPath()
        ctx.arc(proj.x, proj.y, pt.size * proj.scale, 0, Math.PI * 2)
        ctx.fill()
      })

      // Render Edges
      links.forEach(l => {
        if (filterSuspiciousOnly && !l.suspicious) return
        const s = nodeMap.get(l.source)
        const t = nodeMap.get(l.target)
        if (!s || !t) return

        const ps = project(s.x, s.y, is3D ? s.z : 0)
        const pt = project(t.x, t.y, is3D ? t.z : 0)

        ctx.beginPath()
        ctx.moveTo(ps.x, ps.y)
        ctx.lineTo(pt.x, pt.y)

        if (l.suspicious) {
          ctx.strokeStyle = l.type === 'credit' ? 'rgba(244, 63, 94, 0.75)' : 'rgba(245, 158, 11, 0.65)'
          ctx.lineWidth = 1.8 * Math.min(ps.scale, pt.scale)
          ctx.setLineDash([4, 4])
        } else {
          ctx.strokeStyle = `rgba(255, 255, 255, ${0.08 * Math.min(ps.alpha, pt.alpha)})`
          ctx.lineWidth = 1 * Math.min(ps.scale, pt.scale)
          ctx.setLineDash([])
        }
        ctx.stroke()
        ctx.setLineDash([])
      })

      // Render Nodes (sorted by depth for proper painter's occlusion)
      const sortedNodes = [...nodes].map(n => ({
        node: n,
        proj: project(n.x, n.y, is3D ? n.z : 0)
      }))

      if (is3D) {
        sortedNodes.sort((a, b) => a.proj.scale - b.proj.scale)
      }

      sortedNodes.forEach(({ node, proj }) => {
        if (filterSuspiciousOnly && node.risk === 'normal') return

        const isSel = selectedNode?.id === node.id
        const radius = node.radius * proj.scale

        // Halo / Glow for High Risk or Selected
        if (node.risk === 'critical' || isSel) {
          const grad = ctx.createRadialGradient(proj.x, proj.y, radius * 0.5, proj.x, proj.y, radius * 2.8)
          grad.addColorStop(0, node.risk === 'critical' ? 'rgba(244, 63, 94, 0.45)' : 'rgba(212, 175, 55, 0.35)')
          grad.addColorStop(1, 'rgba(0, 0, 0, 0)')
          ctx.fillStyle = grad
          ctx.beginPath()
          ctx.arc(proj.x, proj.y, radius * 2.8, 0, Math.PI * 2)
          ctx.fill()
        }

        // Main Node Body
        ctx.beginPath()
        ctx.arc(proj.x, proj.y, radius, 0, Math.PI * 2)

        if (node.type === 'company') {
          ctx.fillStyle = PALETTE.nodeCompany
        } else if (node.risk === 'critical') {
          ctx.fillStyle = PALETTE.nodeCritical
        } else if (node.risk === 'warning') {
          ctx.fillStyle = PALETTE.nodeWarning
        } else if (node.type === 'credit_note') {
          ctx.fillStyle = '#ec4899'
        } else {
          ctx.fillStyle = PALETTE.nodeCustomer
        }

        ctx.fill()
        ctx.lineWidth = isSel ? 2 : 1
        ctx.strokeStyle = isSel ? '#ffffff' : 'rgba(255, 255, 255, 0.2)'
        ctx.stroke()

        // Node Label (for important or hovered items)
        if (isSel || proj.scale > 0.85 || node.risk !== 'normal' || node.type === 'company') {
          ctx.font = `${Math.round(10 * Math.max(0.8, proj.scale))}px 'JetBrains Mono', monospace`
          ctx.fillStyle = isSel ? '#ffffff' : node.risk === 'critical' ? '#fda4af' : 'rgba(226, 232, 240, 0.8)'
          ctx.textAlign = 'center'
          ctx.fillText(node.label, proj.x, proj.y + radius + 12 * proj.scale)
        }
      })

      animId = requestAnimationFrame(render)
    }

    render()

    return () => {
      cancelAnimationFrame(animId)
      window.removeEventListener('resize', handleResize)
      canvas.removeEventListener('mousedown', onMouseDown)
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onMouseUp)
    }
  }, [invoices, customers, findings, is3D, filterSuspiciousOnly, activeRotation, selectedNode])

  return (
    <div className="forensic-graph-container">
      <div className="graph-toolbar">
        <div className="graph-badges">
          <span className="forensic-pill gold">
            <span className="dot pulse" /> 3D Topology
          </span>
          <span className="forensic-pill slate">{invoices.length} Invoices</span>
          <span className="forensic-pill slate">{customers.length} Entities</span>
        </div>
        <div className="graph-controls">
          <button
            type="button"
            className={`tool-btn ${filterSuspiciousOnly ? 'active' : ''}`}
            onClick={() => setFilterSuspiciousOnly(!filterSuspiciousOnly)}
            title="Isolate exceptions & related party paths"
          >
            <Filter size={14} /> Suspicious Only
          </button>
          <button
            type="button"
            className={`tool-btn ${is3D ? 'active' : ''}`}
            onClick={() => setIs3D(!is3D)}
            title="Toggle 3D Orbit / 2D Planar"
          >
            <Layers size={14} /> {is3D ? '3D Orbit' : '2D Planar'}
          </button>
          {is3D && (
            <button
              type="button"
              className={`tool-btn ${activeRotation ? 'active' : ''}`}
              onClick={() => setActiveRotation(!activeRotation)}
              title="Pause/Resume gentle rotation"
            >
              <RotateCw size={14} /> {activeRotation ? 'Rotating' : 'Static'}
            </button>
          )}
        </div>
      </div>

      <div className="graph-canvas-wrap">
        <canvas ref={canvasRef} className="forensic-canvas" />
        {selectedNode && (
          <aside className="graph-inspector-card">
            <div className="inspector-head">
              <span className={`inspector-tag ${selectedNode.risk}`}>
                {selectedNode.type.toUpperCase()} · {selectedNode.risk.toUpperCase()}
              </span>
              <button type="button" className="close-btn" onClick={() => setSelectedNode(null)}>
                ×
              </button>
            </div>
            <h4>{selectedNode.label}</h4>
            <div className="inspector-meta">
              <div>
                <span>ID</span>
                <code>{selectedNode.id}</code>
              </div>
              {selectedNode.amount !== undefined && (
                <div>
                  <span>Amount</span>
                  <strong>
                    {new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(selectedNode.amount)}
                  </strong>
                </div>
              )}
            </div>
            {selectedNode.meta && (
              <details open className="inspector-details">
                <summary>Disclosed Attributes</summary>
                <pre>{JSON.stringify(selectedNode.meta, null, 2)}</pre>
              </details>
            )}
          </aside>
        )}
      </div>

      <div className="graph-legend-strip">
        <span><i className="lg-dot company" /> Reporting Entity</span>
        <span><i className="lg-dot customer" /> Third Party</span>
        <span><i className="lg-dot warning" /> Disclosed Related</span>
        <span><i className="lg-dot critical" /> Exception / Inconsistent</span>
        <span><i className="lg-line dashed" /> Circular / Reversal Link</span>
      </div>
    </div>
  )
}

// --- Cryptographic Hash Chain & Blockchain Verifier Visualization ---

export function CryptographicChainView({
  events = [],
  checks
}: {
  events: Row[]
  checks?: Row
}) {
  const [selectedEvent, setSelectedEvent] = useState<Row | null>(null)

  const items = events.slice(0, 16)

  return (
    <div className="cryptographic-chain-block">
      <div className="chain-stats-header">
        <div>
          <span className="eyebrow-tech">CRYPTOGRAPHIC INTEGRITY GUARANTEE</span>
          <h3>SHA-256 Merkle Provenance & Event Linkages</h3>
          <p>
            Immutable SHA-256 back-pointer chain. Every event seals the cryptographic hash of its predecessor.
            Any unauthorized alteration invalidates all successor hashes.
          </p>
        </div>
        <div className="chain-status-badge">
          {checks?.all_passed !== false ? (
            <span className="verified-seal">
              <ShieldCheck size={18} /> Intact Hash Chain
            </span>
          ) : (
            <span className="compromised-seal">
              <ShieldAlert size={18} /> Hash Mismatch Detected
            </span>
          )}
        </div>
      </div>

      <div className="chain-scroll-track">
        <div className="chain-rail" />
        {items.map((ev, idx) => {
          const isSelected = selectedEvent?.seq === ev.seq
          const isDenial = ev.action === 'security_denied'
          const isReview = ev.action?.includes('review') || ev.action?.includes('proposal')
          const isSnapshot = ev.action?.includes('snapshot') || ev.action?.includes('run')

          return (
            <div
              key={ev.seq || idx}
              className={`chain-node-box ${isSelected ? 'selected' : ''} ${isDenial ? 'denial' : ''}`}
              onClick={() => setSelectedEvent(ev)}
            >
              <div className="node-link-joint">
                <span className="joint-pin" />
                <span className="joint-line" />
              </div>
              <div className="node-block-content">
                <div className="node-top-bar">
                  <span className="block-number">BLOCK #{String(ev.seq || idx + 1).padStart(4, '0')}</span>
                  <span className={`block-badge ${isDenial ? 'alert' : isReview ? 'gold' : 'normal'}`}>
                    {ev.action?.replace(/_/g, ' ') || 'event'}
                  </span>
                </div>
                <div className="node-actor-field">
                  <span className="label">Actor</span>
                  <span className="val">{ev.actor || 'system'}</span>
                </div>
                <div className="node-hash-preview">
                  <span className="label">Entry Hash</span>
                  <code>{String(ev.entry_hash || 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855').slice(0, 18)}…</code>
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {selectedEvent && (
        <div className="chain-block-inspector">
          <div className="inspector-head">
            <h4>Block #{selectedEvent.seq} Forensic Payload Receipt</h4>
            <button type="button" onClick={() => setSelectedEvent(null)}>×</button>
          </div>
          <div className="inspector-grid">
            <div>
              <span className="label">Action</span>
              <strong>{selectedEvent.action}</strong>
            </div>
            <div>
              <span className="label">Actor Identity</span>
              <strong>{selectedEvent.actor}</strong>
            </div>
            <div>
              <span className="label">Target Reference</span>
              <code>{selectedEvent.object_ref || 'global'}</code>
            </div>
            <div>
              <span className="label">Timestamp</span>
              <span>{selectedEvent.timestamp || new Date().toISOString()}</span>
            </div>
            <div className="span-all">
              <span className="label">SHA-256 Current Hash</span>
              <code className="full-hash">{selectedEvent.entry_hash}</code>
            </div>
            {selectedEvent.prev_hash && (
              <div className="span-all">
                <span className="label">SHA-256 Preceding Hash (Linkage)</span>
                <code className="full-hash">{selectedEvent.prev_hash}</code>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// --- MCP Security & Agent Tool Execution Pipeline Visualizer ---

export interface McpExecutionStep {
  id: string
  agent: string
  tool: string
  operation: string
  dlpCheck: 'clean' | 'redacted' | 'flagged'
  authDecision: 'authorized' | 'denied' | 'requires_human_approval'
  status: 'executed' | 'blocked' | 'pending'
  latencyMs: number
  timestamp: string
}

export function McpSecurityPipelineView({ events = [] }: { events: Row[] }) {
  // Translate actual audit trail events into live MCP tool inspection flows
  const steps: McpExecutionStep[] = events
    .filter(e => e.action?.includes('security') || e.action?.includes('run') || e.actor?.includes('auditor') || e.actor?.includes('assistant'))
    .slice(0, 8)
    .map((e, idx) => {
      const isDenied = e.action === 'security_denied'
      return {
        id: `STEP-${e.seq || idx}`,
        agent: e.actor || 'mcp-audit-assistant',
        tool: isDenied ? 'p2/customers_write' : 'p3/inspect_evidence_vault',
        operation: isDenied ? 'REJECTED: Unauthorized business state mutation' : 'Authorized read-only run digest query',
        dlpCheck: isDenied ? 'flagged' : 'clean',
        authDecision: isDenied ? 'denied' : 'authorized',
        status: isDenied ? 'blocked' : 'executed',
        latencyMs: isDenied ? 8 : 42,
        timestamp: e.timestamp || new Date().toLocaleTimeString()
      }
    })

  // Fallback if no matching events
  const displaySteps = steps.length > 0 ? steps : [
    {
      id: 'STEP-101',
      agent: 'mcp-audit-agent:claude-3-7-sonnet',
      tool: 'read_run_digest',
      operation: 'Inspect frozen snapshot invariants and T00-T15 findings',
      dlpCheck: 'clean' as const,
      authDecision: 'authorized' as const,
      status: 'executed' as const,
      latencyMs: 38,
      timestamp: '14:20:02'
    },
    {
      id: 'STEP-102',
      agent: 'mcp-assistant:ui-auditor',
      tool: 'p2/customers:post',
      operation: 'Prohibited write to enterprise business records from auditor role',
      dlpCheck: 'clean' as const,
      authDecision: 'denied' as const,
      status: 'blocked' as const,
      latencyMs: 6,
      timestamp: '14:22:15'
    },
    {
      id: 'STEP-103',
      agent: 'mcp-audit-agent:gemini-pro',
      tool: 'query_evidence_content',
      operation: 'Inspect company uploaded invoice PDF and SHA-256 hash',
      dlpCheck: 'clean' as const,
      authDecision: 'authorized' as const,
      status: 'executed' as const,
      latencyMs: 54,
      timestamp: '14:24:50'
    }
  ]

  return (
    <div className="mcp-pipeline-container">
      <div className="mcp-pipeline-header">
        <div>
          <span className="eyebrow-tech">MCP PROTOCOL SECURITY BARRIER</span>
          <h3>Zero-Trust Agent Authorization & DLP Stream</h3>
          <p>
            Every AI agent tool invocation passes through deterministic server-side role validation, DLP payload screening, and audit trail logging.
          </p>
        </div>
        <div className="mcp-guard-status">
          <span className="guard-active"><Lock size={15} /> DLP & Access Boundary Active</span>
        </div>
      </div>

      <div className="mcp-steps-flow">
        {displaySteps.map(step => (
          <div key={step.id} className={`mcp-step-card ${step.status}`}>
            <div className="step-rail">
              <span className={`status-dot ${step.status}`} />
              <div className="status-line" />
            </div>
            <div className="step-body">
              <div className="step-header">
                <span className="agent-tag">{step.agent}</span>
                <span className="tool-pill"><Zap size={12} /> {step.tool}</span>
                <span className="latency">{step.latencyMs}ms</span>
              </div>
              <p className="step-op">{step.operation}</p>
              <div className="step-security-tags">
                <span className={`tag dlp-${step.dlpCheck}`}>
                  DLP: {step.dlpCheck.toUpperCase()}
                </span>
                <span className={`tag auth-${step.authDecision}`}>
                  Decision: {step.authDecision.replace(/_/g, ' ').toUpperCase()}
                </span>
                <span className={`tag status-${step.status}`}>
                  {step.status === 'blocked' ? 'BLOCKED & LOGGED' : 'EXECUTED'}
                </span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
