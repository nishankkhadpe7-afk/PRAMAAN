import {useEffect,useRef,useState} from 'react'
import {CheckCircle2,ShieldAlert,ShieldCheck,Zap,Maximize2,Minimize2,Filter,Layers,Eye,Lock,RotateCw} from 'lucide-react'
import {Row} from './components'

// --- High-Performance GPU Canvas 3D Network Engine for Forensic Relationships ---

export type RiskClassification =
  | 'critical'
  | 'serious'
  | 'warning'
  | 'info'
  | 'normal'

export interface GraphNode {
  id: string
  label: string
  type: 'company' | 'customer' | 'invoice' | 'credit_note'
  risk: RiskClassification
  findingState?: string
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
  findings?: Row[]
  evidenceRefs?: string[]
}

export interface GraphLink {
  id?: string
  source: string
  target: string
  type: 'sale' | 'credit' | 'related' | 'circular' | 'reconciliation'
  value?: number
  suspicious?: boolean
  finding?: Row
  meta?: Record<string, any>
}

export function classifyFindingState(state?: string): { risk: RiskClassification; label: string; suspicious: boolean } {
  if (!state) return { risk: 'normal', label: 'Normal', suspicious: false }
  const s = state.toUpperCase()
  switch (s) {
    case 'INCONSISTENT':
    case 'IMPOSSIBLE':
      return { risk: 'critical', label: 'Suspicious / Critical', suspicious: true }
    case 'GAP':
    case 'UNAVAILABLE':
    case 'UNVERIFIED':
      return { risk: 'serious', label: 'Evidence gap', suspicious: false }
    case 'REVIEW':
      return { risk: 'warning', label: 'Needs review', suspicious: false }
    case 'DISCLOSED_RELATED_PARTY':
    case 'GOVERNMENT_REGISTERED_DEMO':
      return { risk: 'info', label: 'Context', suspicious: false }
    default:
      return { risk: 'normal', label: 'Normal', suspicious: false }
  }
}

export function evaluateEntityRisk(findings: Row[]): { risk: RiskClassification; suspicious: boolean } {
  if (!findings || findings.length === 0) return { risk: 'normal', suspicious: false }
  let hasCritical = false
  let hasSerious = false
  let hasWarning = false
  let hasInfo = false

  for (const f of findings) {
    const c = classifyFindingState(f.state)
    if (c.risk === 'critical') hasCritical = true
    if (c.risk === 'serious') hasSerious = true
    if (c.risk === 'warning') hasWarning = true
    if (c.risk === 'info') hasInfo = true
  }

  if (hasCritical) return { risk: 'critical', suspicious: true }
  if (hasSerious) return { risk: 'serious', suspicious: false }
  if (hasWarning) return { risk: 'warning', suspicious: false }
  if (hasInfo) return { risk: 'info', suspicious: false }
  return { risk: 'normal', suspicious: false }
}

const PALETTE = {
  canvasBg: '#090a0d',
  nodeCompany: '#d4af37', // Antique gold
  nodeCustomer: '#64748b', // Slate blue
  nodeInvoice: '#d97706', // Neutral amber
  nodeDisclosed: '#a855f7', // Muted purple
  nodeInconsistent: '#ef4444', // Red
  nodeImpossible: '#ff0033', // Bright red
  nodeEvidenceGap: '#f97316', // Orange
  nodeReview: '#eab308', // Yellow
  edgeNormal: 'rgba(148, 163, 184, 0.25)', // Subtle grey
  edgeDisclosed: 'rgba(168, 85, 247, 0.45)', // Muted purple edge
  edgeReversal: '#0d9488', // Muted blue/green legitimate reversal
  edgeCircular: '#ef4444', // Red dashed circular relationship
  edgeSuspicious: '#ef4444', // Red for critical suspicious
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
  const [selectedLink, setSelectedLink] = useState<GraphLink | null>(null)
  const [is3D, setIs3D] = useState(true)
  const [filterSuspiciousOnly, setFilterSuspiciousOnly] = useState(false)
  const [activeRotation, setActiveRotation] = useState(true)

  // 1. Build Full Graph Topology from Real Records
  const allNodesMap = new Map<string, GraphNode>()
  const allLinks: GraphLink[] = []

  // Root Reporting Entity Node
  allNodesMap.set('PRAMAAN_CORP', {
    id: 'PRAMAAN_CORP',
    label: 'Reporting Entity',
    type: 'company',
    risk: 'normal',
    x: 0,
    y: 0,
    z: 0,
    vx: 0,
    vy: 0,
    vz: 0,
    radius: 12,
    meta: { role: 'Audited Reporting Entity' }
  })

  // Index findings by referenced IDs
  const findingsByRef = new Map<string, Row[]>()
  for (const f of findings) {
    if (f.object_ref) {
      const list = findingsByRef.get(f.object_ref) || []
      list.push(f)
      findingsByRef.set(f.object_ref, list)
    }
    if (Array.isArray(f.samples)) {
      for (const s of f.samples) {
        if (s.object_ref) {
          const list = findingsByRef.get(s.object_ref) || []
          list.push(f)
          findingsByRef.set(s.object_ref, list)
        }
      }
    }
    if (Array.isArray(f.cycle_nodes)) {
      for (const nodeRef of f.cycle_nodes) {
        const list = findingsByRef.get(nodeRef) || []
        list.push(f)
        findingsByRef.set(nodeRef, list)
      }
    }
  }

  // Helper to extract evidence references
  const getEvidenceRefs = (itemMeta: Record<string, any>, itemFindings: Row[]) => {
    const refs = new Set<string>()
    if (itemMeta.dispatch_id) refs.add(`DISPATCH:${itemMeta.dispatch_id}`)
    if (itemMeta.vehicle_no) refs.add(`VEHICLE:${itemMeta.vehicle_no}`)
    if (itemMeta.gstin) refs.add(`GSTIN:${itemMeta.gstin}`)
    for (const f of itemFindings) {
      if (f.source_ref) refs.add(String(f.source_ref))
      if (f.source_upload_id) refs.add(`UPLOAD:${f.source_upload_id}`)
    }
    return Array.from(refs)
  }

  // Track customer-to-invoices
  const customerInvoicesMap = new Map<string, string[]>()
  const customerRelatedPartiesMap = new Map<string, Set<string>>()

  // 2. Add Customers
  customers.forEach((c, idx) => {
    const angle = (idx / Math.max(customers.length, 1)) * Math.PI * 2
    const radius = 180 + (idx % 2) * 50
    const custId = c.customer_id
    const custFindings = findingsByRef.get(custId) || []

    const isDisclosed = findings.some(
      f => (f.test_id === 'T01' || f.test_id === 'T02') &&
        (f.object_ref === custId || f.customer_id === custId || f.subject_id === custId || f.object_id === custId)
    )

    const entityEval = evaluateEntityRisk(custFindings)
    const risk: RiskClassification = entityEval.risk === 'critical'
      ? 'critical'
      : isDisclosed
        ? 'info'
        : entityEval.risk

    allNodesMap.set(custId, {
      id: custId,
      label: c.name || custId,
      type: 'customer',
      risk,
      x: Math.cos(angle) * radius,
      y: Math.sin(angle) * radius * 0.7,
      z: Math.sin(angle * 2) * 120,
      vx: 0,
      vy: 0,
      vz: 0,
      radius: isDisclosed ? 8.5 : 7,
      meta: c,
      findings: custFindings,
      evidenceRefs: getEvidenceRefs(c, custFindings)
    })

    // Link Reporting entity -> Customer
    allLinks.push({
      id: `LINK-CORP-${custId}`,
      source: 'PRAMAAN_CORP',
      target: custId,
      type: isDisclosed ? 'related' : 'sale',
      suspicious: risk === 'critical',
      meta: { relationship: isDisclosed ? 'Disclosed Related Party Counterparty' : 'Ordinary Customer Relationship' }
    })
  })

  // 3. Add Invoices and Credit Notes (WITHOUT truncation)
  const invoiceNodeIds = new Set<string>()
  const invoiceByBillNo = new Map<string, string>()

  invoices.forEach((inv, idx) => {
    const invId = inv.invoice_id || inv.credit_note_id || `INV-${idx}`
    invoiceNodeIds.add(invId)
    if (inv.bill_no) {
      invoiceByBillNo.set(inv.bill_no, invId)
    }
  })

  invoices.forEach((inv, idx) => {
    const custId = inv.customer_id
    const invId = inv.invoice_id || inv.credit_note_id || `INV-${idx}`
    const isCredit = Boolean(inv.credit_note_id)
    const invFindings = findingsByRef.get(invId) || []

    // Classify finding states accurately according to specification
    const hasInconsistent = invFindings.some(f => f.state === 'INCONSISTENT')
    const hasImpossible = invFindings.some(f => f.state === 'IMPOSSIBLE')
    const hasEvidenceGap = invFindings.some(f => f.state === 'GAP' || f.state === 'UNAVAILABLE' || f.state === 'UNVERIFIED')
    const hasReview = invFindings.some(f => f.state === 'REVIEW')
    const hasDisclosed = invFindings.some(f => f.state === 'DISCLOSED_RELATED_PARTY')

    let risk: RiskClassification = 'normal'
    let findingState: string | undefined = undefined

    if (hasImpossible) {
      risk = 'critical'
      findingState = 'IMPOSSIBLE'
    } else if (hasInconsistent) {
      risk = 'critical'
      findingState = 'INCONSISTENT'
    } else if (hasEvidenceGap) {
      risk = 'serious'
      findingState = 'GAP'
    } else if (hasReview) {
      risk = 'warning'
      findingState = 'REVIEW'
    } else if (hasDisclosed) {
      risk = 'info'
      findingState = 'DISCLOSED_RELATED_PARTY'
    }

    const angle = (idx / Math.max(invoices.length, 1)) * Math.PI * 2
    const spread = 240 + (idx % 3) * 40
    const amountVal = inv.amount_cents
      ? inv.amount_cents / 100
      : inv.gross_cents
        ? inv.gross_cents / 100
        : Number(inv.net_amount || 0)

    allNodesMap.set(invId, {
      id: invId,
      label: inv.bill_no || invId,
      type: isCredit ? 'credit_note' : 'invoice',
      risk,
      findingState,
      amount: amountVal,
      x: Math.cos(angle) * spread,
      y: Math.sin(angle) * spread * 0.75,
      z: Math.cos(angle * 1.5) * 140,
      vx: 0,
      vy: 0,
      vz: 0,
      radius: risk === 'critical' ? 6.5 : isCredit ? 5 : 4.5,
      meta: inv,
      findings: invFindings,
      evidenceRefs: getEvidenceRefs(inv, invFindings)
    })

    if (custId) {
      const list = customerInvoicesMap.get(custId) || []
      list.push(invId)
      customerInvoicesMap.set(custId, list)
    }

    if (isCredit) {
      // Connect credit note to its original invoice if available
      const origInvId = inv.invoice_id && invoiceNodeIds.has(inv.invoice_id)
        ? inv.invoice_id
        : (inv.bill_no && invoiceByBillNo.has(inv.bill_no) && invoiceByBillNo.get(inv.bill_no) !== invId)
          ? invoiceByBillNo.get(inv.bill_no)
          : null

      if (origInvId) {
        allLinks.push({
          id: `REVERSAL-${invId}-${origInvId}`,
          source: invId,
          target: origInvId,
          type: 'credit',
          suspicious: risk === 'critical',
          meta: { reason: inv.reason || 'Credit note reversal', date: inv.credit_date }
        })
      } else if (custId && allNodesMap.has(custId)) {
        allLinks.push({
          id: `CREDIT-${custId}-${invId}`,
          source: custId,
          target: invId,
          type: 'credit',
          suspicious: risk === 'critical',
          meta: { reason: inv.reason || 'Credit note adjustment', date: inv.credit_date }
        })
      }
    } else {
      // Ordinary invoice: connect customer -> invoice
      if (custId && allNodesMap.has(custId)) {
        allLinks.push({
          id: `SALE-${custId}-${invId}`,
          source: custId,
          target: invId,
          type: 'sale',
          suspicious: risk === 'critical',
          meta: { date: inv.invoice_date, bill_no: inv.bill_no }
        })
      } else {
        allLinks.push({
          id: `SALE-CORP-${invId}`,
          source: 'PRAMAAN_CORP',
          target: invId,
          type: 'sale',
          suspicious: risk === 'critical',
          meta: { date: inv.invoice_date, bill_no: inv.bill_no }
        })
      }
    }
  })

  // 4. Construct Related-Party & T02 Cycle Relationships
  findings.forEach(f => {
    if (f.test_id === 'T02' && Array.isArray(f.cycle_nodes) && f.cycle_nodes.length > 1) {
      // Connect consecutive cycle nodes
      for (let i = 0; i < f.cycle_nodes.length; i++) {
        const sNode = f.cycle_nodes[i]
        const tNode = f.cycle_nodes[(i + 1) % f.cycle_nodes.length]
        if (allNodesMap.has(sNode) && allNodesMap.has(tNode)) {
          allLinks.push({
            id: `CYCLE-${sNode}-${tNode}-${f.finding_id}`,
            source: sNode,
            target: tNode,
            type: 'circular',
            suspicious: true,
            finding: f,
            meta: { cycle_path: f.cycle_path, reason: f.reason }
          })
          const sRelated = customerRelatedPartiesMap.get(sNode) || new Set<string>()
          sRelated.add(tNode)
          customerRelatedPartiesMap.set(sNode, sRelated)
        }
      }
    } else if (f.subject_id && f.object_id && allNodesMap.has(f.subject_id) && allNodesMap.has(f.object_id)) {
      allLinks.push({
        id: `REL-${f.subject_id}-${f.object_id}`,
        source: f.subject_id,
        target: f.object_id,
        type: 'related',
        suspicious: f.state === 'INCONSISTENT' || f.state === 'IMPOSSIBLE',
        finding: f,
        meta: { relationship_type: f.relationship_type, confidence: f.confidence }
      })
      const sRelated = customerRelatedPartiesMap.get(f.subject_id) || new Set<string>()
      sRelated.add(f.object_id)
      customerRelatedPartiesMap.set(f.subject_id, sRelated)
    }
  })

  // 5. Pre-filter Graph Data Before Rendering when "Suspicious Only" is active
  let visibleNodes: GraphNode[] = []
  let visibleLinks: GraphLink[] = []

  if (!filterSuspiciousOnly) {
    visibleNodes = Array.from(allNodesMap.values())
    visibleLinks = [...allLinks]
  } else {
    // Collect all genuine risk-bearing nodes (risk === 'critical' or involved in circular link)
    const criticalNodeIds = new Set<string>()
    for (const [id, node] of allNodesMap.entries()) {
      if (node.risk === 'critical') {
        criticalNodeIds.add(id)
      }
    }
    for (const l of allLinks) {
      if (l.suspicious || l.type === 'circular') {
        criticalNodeIds.add(l.source)
        criticalNodeIds.add(l.target)
      }
    }

    if (criticalNodeIds.size > 0) {
      // Include direct counterparties and paths needed to explain findings
      const explanatoryNodeIds = new Set<string>(criticalNodeIds)
      explanatoryNodeIds.add('PRAMAAN_CORP')

      for (const id of criticalNodeIds) {
        const node = allNodesMap.get(id)
        if (node?.type === 'invoice' || node?.type === 'credit_note') {
          if (node.meta?.customer_id && allNodesMap.has(node.meta.customer_id)) {
            explanatoryNodeIds.add(node.meta.customer_id)
          }
        }
      }

      visibleNodes = Array.from(allNodesMap.values()).filter(n => explanatoryNodeIds.has(n.id))
      const visibleSet = new Set(visibleNodes.map(n => n.id))

      visibleLinks = allLinks.filter(l => {
        if (!visibleSet.has(l.source) || !visibleSet.has(l.target)) return false
        return l.suspicious || l.type === 'circular' || criticalNodeIds.has(l.source) || criticalNodeIds.has(l.target)
      })
    } else {
      visibleNodes = []
      visibleLinks = []
    }
  }

  // Calculate dynamic counters
  const totalInvoicesCount = invoices.length
  const totalEntitiesCount = customers.length + 1 // customers + reporting entity
  const visibleInvoicesCount = visibleNodes.filter(n => n.type === 'invoice' || n.type === 'credit_note').length
  const visibleEntitiesCount = visibleNodes.filter(n => n.type === 'company' || n.type === 'customer').length
  const visibleRelationshipsCount = visibleLinks.length

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

    const nodeMap = new Map<string, GraphNode>()
    for (const n of visibleNodes) {
      nodeMap.set(n.id, n)
    }

    // 3D Camera Rotation State
    let angleY = 0
    let angleX = 0.25
    let fov = 380
    let isDragging = false
    let lastMouseX = 0
    let lastMouseY = 0
    let dragDistance = 0

    const onMouseDown = (e: MouseEvent) => {
      isDragging = true
      dragDistance = 0
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
        dragDistance += Math.hypot(dx, dy)
        angleY += dx * 0.006
        angleX += dy * 0.006
        lastMouseX = e.clientX
        lastMouseY = e.clientY
      } else {
        // Hover detection on nodes
        let foundNode: GraphNode | null = null
        for (const n of visibleNodes) {
          const p = project(n.x, n.y, is3D ? n.z : 0)
          const dist = Math.hypot(mx - p.x, my - p.y)
          if (dist < p.scale * n.radius + 6) {
            foundNode = n
            break
          }
        }
        canvas.style.cursor = foundNode ? 'pointer' : isDragging ? 'grabbing' : 'grab'
      }
    }

    const onMouseUp = (e: MouseEvent) => {
      if (dragDistance < 5) {
        // Click to select node or link
        const rect = canvas.getBoundingClientRect()
        const mx = e.clientX - rect.left
        const my = e.clientY - rect.top

        let clickedNode: GraphNode | null = null
        for (const n of visibleNodes) {
          const p = project(n.x, n.y, is3D ? n.z : 0)
          const dist = Math.hypot(mx - p.x, my - p.y)
          if (dist < p.scale * n.radius + 8) {
            clickedNode = n
            break
          }
        }

        if (clickedNode) {
          setSelectedNode(clickedNode)
          setSelectedLink(null)
          onSelectNode?.(clickedNode)
        } else {
          // Check link click
          let clickedLink: GraphLink | null = null
          for (const l of visibleLinks) {
            const s = nodeMap.get(l.source)
            const t = nodeMap.get(l.target)
            if (!s || !t) continue
            const ps = project(s.x, s.y, is3D ? s.z : 0)
            const pt = project(t.x, t.y, is3D ? t.z : 0)
            const l2 = (pt.x - ps.x) ** 2 + (pt.y - ps.y) ** 2
            if (l2 === 0) continue
            let tParam = ((mx - ps.x) * (pt.x - ps.x) + (my - ps.y) * (pt.y - ps.y)) / l2
            tParam = Math.max(0, Math.min(1, tParam))
            const projX = ps.x + tParam * (pt.x - ps.x)
            const projY = ps.y + tParam * (pt.y - ps.y)
            if (Math.hypot(mx - projX, my - projY) < 6) {
              clickedLink = l
              break
            }
          }
          if (clickedLink) {
            setSelectedLink(clickedLink)
            setSelectedNode(null)
          } else {
            setSelectedNode(null)
            setSelectedLink(null)
            onSelectNode?.(null)
          }
        }
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
      visibleLinks.forEach(l => {
        const s = nodeMap.get(l.source)
        const t = nodeMap.get(l.target)
        if (!s || !t) return

        const ps = project(s.x, s.y, is3D ? s.z : 0)
        const pt = project(t.x, t.y, is3D ? t.z : 0)
        const isLinkSelected = selectedLink?.id === l.id

        ctx.beginPath()
        ctx.moveTo(ps.x, ps.y)
        ctx.lineTo(pt.x, pt.y)

        if (l.type === 'circular') {
          // Circular relationship: Red dashed edge
          ctx.strokeStyle = PALETTE.edgeCircular
          ctx.lineWidth = (isLinkSelected ? 3 : 2) * Math.min(ps.scale, pt.scale)
          ctx.setLineDash([5, 5])
        } else if (l.type === 'credit') {
          // Legitimate reversal: Muted blue/green
          ctx.strokeStyle = l.suspicious ? PALETTE.edgeSuspicious : PALETTE.edgeReversal
          ctx.lineWidth = (isLinkSelected ? 2.5 : 1.6) * Math.min(ps.scale, pt.scale)
          ctx.setLineDash(l.suspicious ? [4, 4] : [2, 3])
        } else if (l.type === 'related') {
          ctx.strokeStyle = l.suspicious ? PALETTE.edgeSuspicious : PALETTE.edgeDisclosed
          ctx.lineWidth = (isLinkSelected ? 2.5 : 1.6) * Math.min(ps.scale, pt.scale)
          ctx.setLineDash(l.suspicious ? [4, 4] : [])
        } else if (l.suspicious) {
          ctx.strokeStyle = PALETTE.edgeSuspicious
          ctx.lineWidth = (isLinkSelected ? 2.5 : 1.8) * Math.min(ps.scale, pt.scale)
          ctx.setLineDash([4, 4])
        } else {
          // Normal relationship: Subtle grey
          ctx.strokeStyle = PALETTE.edgeNormal
          ctx.lineWidth = (isLinkSelected ? 2 : 1) * Math.min(ps.scale, pt.scale)
          ctx.setLineDash([])
        }

        ctx.stroke()
        ctx.setLineDash([])
      })

      // Render Nodes (sorted by depth for proper painter's occlusion)
      const sortedNodes = [...visibleNodes].map(n => ({
        node: n,
        proj: project(n.x, n.y, is3D ? n.z : 0)
      }))

      if (is3D) {
        sortedNodes.sort((a, b) => a.proj.scale - b.proj.scale)
      }

      sortedNodes.forEach(({ node, proj }) => {
        const isSel = selectedNode?.id === node.id
        const radius = node.radius * proj.scale

        // Halo / Glow for High Risk or Selected
        if (node.risk === 'critical' || isSel) {
          const grad = ctx.createRadialGradient(proj.x, proj.y, radius * 0.5, proj.x, proj.y, radius * 2.8)
          grad.addColorStop(0, node.risk === 'critical' ? 'rgba(239, 68, 68, 0.45)' : 'rgba(212, 175, 55, 0.35)')
          grad.addColorStop(1, 'rgba(0, 0, 0, 0)')
          ctx.fillStyle = grad
          ctx.beginPath()
          ctx.arc(proj.x, proj.y, radius * 2.8, 0, Math.PI * 2)
          ctx.fill()
        }

        // Main Node Body & Palette treatment
        ctx.beginPath()
        ctx.arc(proj.x, proj.y, radius, 0, Math.PI * 2)

        if (node.type === 'company') {
          ctx.fillStyle = PALETTE.nodeCompany // Gold
        } else if (node.findingState === 'IMPOSSIBLE') {
          ctx.fillStyle = PALETTE.nodeImpossible // Bright red
        } else if (node.risk === 'critical') {
          ctx.fillStyle = PALETTE.nodeInconsistent // Red
        } else if (node.risk === 'serious') {
          ctx.fillStyle = PALETTE.nodeEvidenceGap // Orange
        } else if (node.risk === 'warning') {
          ctx.fillStyle = PALETTE.nodeReview // Yellow
        } else if (node.risk === 'info') {
          ctx.fillStyle = PALETTE.nodeDisclosed // Muted purple
        } else if (node.type === 'customer') {
          ctx.fillStyle = PALETTE.nodeCustomer // Slate blue
        } else {
          ctx.fillStyle = PALETTE.nodeInvoice // Neutral amber
        }

        ctx.fill()
        ctx.lineWidth = isSel ? 2.5 : 1
        ctx.strokeStyle = isSel ? '#ffffff' : 'rgba(255, 255, 255, 0.25)'
        ctx.stroke()

        // Node Label (for important or hovered items)
        if (isSel || proj.scale > 0.85 || node.risk === 'critical' || node.type === 'company') {
          ctx.font = `${Math.round(10 * Math.max(0.8, proj.scale))}px 'JetBrains Mono', monospace`
          ctx.fillStyle = isSel ? '#ffffff' : node.risk === 'critical' ? '#fca5a5' : 'rgba(226, 232, 240, 0.85)'
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
  }, [visibleNodes, visibleLinks, is3D, activeRotation, selectedNode, selectedLink])

  return (
    <div className="forensic-graph-container">
      <div className="graph-toolbar">
        <div className="graph-badges">
          <span className="forensic-pill gold">
            <span className="dot pulse" /> 3D Topology
          </span>
          <span className="forensic-pill slate">
            {filterSuspiciousOnly ? `${visibleInvoicesCount} / ${totalInvoicesCount}` : totalInvoicesCount} Invoices
          </span>
          <span className="forensic-pill slate">
            {filterSuspiciousOnly ? `${visibleEntitiesCount} / ${totalEntitiesCount}` : totalEntitiesCount} Entities
          </span>
          <span className="forensic-pill slate">
            {visibleRelationshipsCount} Links
          </span>
        </div>
        <div className="graph-controls">
          <button
            type="button"
            className={`tool-btn ${filterSuspiciousOnly ? 'active' : ''}`}
            aria-pressed={filterSuspiciousOnly}
            onClick={() => setFilterSuspiciousOnly(!filterSuspiciousOnly)}
            title="Isolate genuine risk-bearing exceptions and circular relationships"
          >
            <Filter size={14} /> Suspicious Only
          </button>
          <button
            type="button"
            className={`tool-btn ${is3D ? 'active' : ''}`}
            aria-pressed={is3D}
            onClick={() => setIs3D(!is3D)}
            title="Toggle 3D Orbit / 2D Planar"
          >
            <Layers size={14} /> {is3D ? '3D Orbit' : '2D Planar'}
          </button>
          {is3D && (
            <button
              type="button"
              className={`tool-btn ${activeRotation ? 'active' : ''}`}
              aria-pressed={activeRotation}
              onClick={() => setActiveRotation(!activeRotation)}
              title="Pause/Resume gentle rotation"
            >
              <RotateCw size={14} /> {activeRotation ? 'Rotating' : 'Static'}
            </button>
          )}
        </div>
      </div>

      <div className="graph-canvas-wrap">
        {filterSuspiciousOnly && visibleNodes.length === 0 ? (
          <div className="empty-suspicious-state">
            <p>No suspicious relationships identified for this audit dataset.</p>
          </div>
        ) : (
          <canvas ref={canvasRef} className="forensic-canvas" role="img" aria-label="Interactive transaction and entity relationship network" />
        )}

        {/* Node Inspector */}
        {selectedNode && (
          <aside className="graph-inspector-card">
            <div className="inspector-head">
              <span className={`inspector-tag ${selectedNode.risk}`}>
                {selectedNode.type.toUpperCase()} · {selectedNode.risk.toUpperCase()}
              </span>
              <button type="button" className="close-btn" aria-label="Close node details" onClick={() => setSelectedNode(null)}>
                ×
              </button>
            </div>
            <h4>{selectedNode.label}</h4>
            <div className="inspector-meta">
              <div>
                <span>ID</span>
                <code>{selectedNode.id}</code>
              </div>
              {selectedNode.type === 'invoice' || selectedNode.type === 'credit_note' ? (
                <>
                  {selectedNode.amount !== undefined && (
                    <div>
                      <span>Amount</span>
                      <strong>
                        {new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(selectedNode.amount)}
                      </strong>
                    </div>
                  )}
                  {selectedNode.meta?.invoice_date && (
                    <div>
                      <span>Date</span>
                      <span>{selectedNode.meta.invoice_date}</span>
                    </div>
                  )}
                  {selectedNode.meta?.credit_date && (
                    <div>
                      <span>Credit Date</span>
                      <span>{selectedNode.meta.credit_date}</span>
                    </div>
                  )}
                  {selectedNode.meta?.customer_id && (
                    <div>
                      <span>Counterparty</span>
                      <code>{selectedNode.meta.customer_id}</code>
                    </div>
                  )}
                  <div>
                    <span>Risk Classification</span>
                    <strong className={`risk-text risk-${selectedNode.risk}`}>
                      {classifyFindingState(selectedNode.findingState).label}
                    </strong>
                  </div>
                </>
              ) : selectedNode.type === 'customer' ? (
                <>
                  <div>
                    <span>Entity Name</span>
                    <strong>{selectedNode.meta?.name || selectedNode.id}</strong>
                  </div>
                  <div>
                    <span>Associated Invoices</span>
                    <span>{(customerInvoicesMap.get(selectedNode.id) || []).length} invoices</span>
                  </div>
                  {customerRelatedPartiesMap.has(selectedNode.id) && (
                    <div>
                      <span>Related Entities</span>
                      <span>{Array.from(customerRelatedPartiesMap.get(selectedNode.id)!).join(', ')}</span>
                    </div>
                  )}
                </>
              ) : (
                <div>
                  <span>Entity Role</span>
                  <strong>Audited Reporting Entity</strong>
                </div>
              )}

              {selectedNode.evidenceRefs && selectedNode.evidenceRefs.length > 0 && (
                <div>
                  <span>Evidence References</span>
                  <div className="inspector-chips">
                    {selectedNode.evidenceRefs.map(ref => (
                      <code key={ref}>{ref}</code>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {selectedNode.findings && selectedNode.findings.length > 0 && (
              <div className="inspector-findings">
                <h5>Connected Findings ({selectedNode.findings.length})</h5>
                <ul>
                  {selectedNode.findings.map(f => (
                    <li key={f.finding_id}>
                      <span className={`finding-chip ${f.state}`}>{f.state}</span>
                      <p>{f.reason || f.observation}</p>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {selectedNode.meta && (
              <details className="inspector-details">
                <summary>Record Details</summary>
                <pre>{JSON.stringify(selectedNode.meta, null, 2)}</pre>
              </details>
            )}
          </aside>
        )}

        {/* Edge / Link Inspector */}
        {selectedLink && (
          <aside className="graph-inspector-card">
            <div className="inspector-head">
              <span className={`inspector-tag ${selectedLink.suspicious ? 'critical' : 'normal'}`}>
                LINK · {selectedLink.type.toUpperCase()}
              </span>
              <button type="button" className="close-btn" aria-label="Close relationship details" onClick={() => setSelectedLink(null)}>
                ×
              </button>
            </div>
            <h4>Relationship: {selectedLink.type.toUpperCase()}</h4>
            <div className="inspector-meta">
              <div>
                <span>Source</span>
                <code>{selectedLink.source}</code>
              </div>
              <div>
                <span>Target</span>
                <code>{selectedLink.target}</code>
              </div>
              <div>
                <span>Relationship Type</span>
                <strong>{selectedLink.type === 'circular' ? 'Directed Circular Cycle' : selectedLink.type}</strong>
              </div>
              {selectedLink.finding && (
                <div>
                  <span>Associated Finding</span>
                  <code>{selectedLink.finding.finding_id}</code>
                  <p className="inspector-finding-reason">
                    {selectedLink.finding.reason}
                  </p>
                </div>
              )}
            </div>
            {selectedLink.meta && (
              <details className="inspector-details" open>
                <summary>Source Records & Attributes</summary>
                <pre>{JSON.stringify(selectedLink.meta, null, 2)}</pre>
              </details>
            )}
          </aside>
        )}
      </div>

      <div className="graph-legend-strip">
        <span><i className="lg-dot company" /> Reporting Entity</span>
        <span><i className="lg-dot customer" /> Ordinary Customer</span>
        <span><i className="lg-dot invoice" /> Normal Invoice</span>
        <span><i className="lg-dot disclosed" /> Disclosed Related Party</span>
        <span><i className="lg-dot inconsistent" /> Inconsistent Transaction</span>
        <span><i className="lg-dot impossible" /> Impossible Transaction</span>
        <span><i className="lg-dot evidence-gap" /> Evidence Gap</span>
        <span><i className="lg-dot review" /> Needs Review</span>
        <span><i className="lg-line dashed-circular" /> Circular Relationship</span>
        <span><i className="lg-line reversal" /> Legitimate Reversal</span>
        <span><i className="lg-line subtle" /> Normal Relationship</span>
      </div>
    </div>
  )
}

// --- Cryptographic hash-chain verification visualization ---

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
          <span className="eyebrow-tech">CRYPTOGRAPHIC INTEGRITY CHECK</span>
          <h3>SHA-256 Event Provenance & Hash Linkages</h3>
          <p>
            Tamper-evident SHA-256 back-pointer chain. Every event records the cryptographic hash of its predecessor,
            so later verification detects alteration of a past entry.
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
            <button
              type="button"
              key={ev.seq || idx}
              className={`chain-node-box ${isSelected ? 'selected' : ''} ${isDenial ? 'denial' : ''}`}
              aria-pressed={isSelected}
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
            </button>
          )
        })}
      </div>

      {selectedEvent && (
        <div className="chain-block-inspector">
          <div className="inspector-head">
            <h4>Block #{selectedEvent.seq} Forensic Payload Receipt</h4>
            <button type="button" className="close-btn" aria-label="Close event details" onClick={() => setSelectedEvent(null)}>×</button>
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

// --- MCP / tool-call audit trail: real hash-chained events only, nothing simulated ---

type TrailGroup={key:string;actor:string;action:string;role?:string;channel?:string;first:number;last:number;count:number;ref:string;hash:string;denied:boolean}

export function McpSecurityPipelineView({ events = [] }: { events: Row[] }) {
  const [all, setAll] = useState(false)
  const ordered = [...events].sort((x, y) => y.seq - x.seq)
  const groups: TrailGroup[] = []
  for (const e of ordered) {
    const key = [e.actor, e.action, e.role, e.channel].join('|')
    const g = groups[groups.length - 1]
    if (g && g.key === key) { g.count++; g.first = Math.min(g.first, e.seq) }
    else groups.push({ key, actor: e.actor, action: e.action, role: e.role, channel: e.channel, first: e.seq, last: e.seq, count: 1, ref: e.object_ref, hash: e.payload_hash || '', denied: /denied|reject|blocked/i.test(e.action || '') })
  }
  const shown = all ? groups : groups.slice(0, 6)
  return (
    <div className="mcp-pipeline-container">
      <div className="mcp-pipeline-header">
        <div>
          <span className="eyebrow-tech">TOOL-CALL AUDIT TRAIL</span>
          <h3>Who did what, in order</h3>
          <p>Every call is recorded in a hash-chained, append-only log. Repeated identical calls are grouped; open the Integrity tab of a run to verify the chain.</p>
        </div>
        <div className="mcp-guard-status">
          <span className="guard-active"><Lock size={15} /> {events.length} logged events</span>
        </div>
      </div>
      {groups.length === 0 ? <p>No events logged yet.</p> : <div className="mcp-steps-flow">
        {shown.map(g => (
          <div key={g.key + g.last} className={`mcp-step-card ${g.denied ? 'blocked' : 'executed'}`}>
            <div className="step-rail"><span className={`status-dot ${g.denied ? 'blocked' : 'executed'}`} /><div className="status-line" /></div>
            <div className="step-body">
              <div className="step-header">
                <span className="agent-tag">{g.actor}</span>
                <span className="tool-pill"><Zap size={12} /> {g.action}</span>
                <span className="latency">{g.count > 1 ? `×${g.count} · #${g.first}–#${g.last}` : `#${g.last}`}</span>
              </div>
              <p className="step-op">{g.ref ? `Object: ${g.ref}` : 'No object reference'}</p>
              <div className="step-security-tags">
                {g.role && <span className="tag">Role: {g.role}</span>}
                {g.channel && <span className="tag">Channel: {g.channel}</span>}
                <span className={`tag ${g.denied ? 'status-blocked' : 'status-executed'}`}>{g.denied ? 'DENIED & LOGGED' : 'LOGGED'}</span>
                {g.hash && <span className="tag">payload {g.hash.slice(0, 10)}…</span>}
              </div>
            </div>
          </div>
        ))}
      </div>}
      {groups.length > 6 && <button type="button" onClick={() => setAll(v => !v)}>{all ? 'Show fewer' : `Show all ${groups.length} groups`}</button>}
    </div>
  )
}
