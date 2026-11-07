import {render,screen,within,waitFor} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {MemoryRouter} from 'react-router-dom'
import {beforeEach,it,expect,vi} from 'vitest'
import {App} from './App'
import {ApiError} from './api'

const session=vi.hoisted(()=>({identity:{subject:'integration-auditor',role:'auditor',human:false},api:{json:vi.fn(),download:vi.fn()},signOut:vi.fn()}))
vi.mock('./session',()=>({useSession:()=>session}))
const context={audit_name:'Cedar Wholesale audit',run_id:'R1',snapshot_hash:'snapshot',selected_upload_id:'REG2',registers:[{upload_id:'REG1',period:'FY26',row_count:1},{upload_id:'REG2',period:'FY26',row_count:2}],invoices:[{invoice_id:'I1'}],result:{period_start:'2025-04-01',period_end:'2026-03-31',ruleset_version:'v1',sampling_seed:'saved-seed',sample_items:[],rule_coverage:{},coverage:{sales_tod:{population_projection_supported:false}}},findings:[{finding_id:'RELATED',test_id:'T01',assertion:'Classification',state:'REVIEW',reason:'A disclosed relationship',samples:[]},{finding_id:'OTHER',test_id:'T04',assertion:'Existence',state:'GAP',reason:'Missing document',samples:[]}]}
function mount(path:string){return render(<MemoryRouter initialEntries={[path]}><App/></MemoryRouter>)}
beforeEach(()=>{session.api.json.mockReset();session.api.download.mockReset();session.api.json.mockImplementation(async(path:string)=>{if(path.startsWith('/ui/runs/R1/context'))return context;if(path.endsWith('/evidence-requests'))return {requests:[]};if(path==='/ui/runs')return {runs:[],packages:[]};throw new Error('Unexpected API path: '+path)})})

it('merges related-party findings and retains the selected register across audit sections',async()=>{
 mount('/auditor/runs/R1/findings?upload=REG2');await screen.findByText('A disclosed relationship',{},{timeout:5000});expect(screen.getByText('Missing document')).toBeInTheDocument();
 const nav=screen.getByRole('navigation',{name:'Audit engagement sections'});expect(within(nav).getAllByRole('link').map(link=>link.textContent)).toEqual(['Summary','Samples','Findings','Workpapers','Integrity']);
 await userEvent.selectOptions(screen.getByLabelText('Finding category'),'related');expect(screen.queryByText('Missing document')).not.toBeInTheDocument();
 await userEvent.click(within(nav).getByRole('link',{name:'Samples'}));await screen.findByRole('heading',{name:'Selected workpaper items'});await userEvent.click(screen.getByRole('button',{name:'Evidence requests'}));await screen.findByRole('heading',{name:'Client evidence requests'});expect(screen.getByLabelText('Snapshotted register for findings and exports')).toHaveValue('REG2');expect(session.api.json).toHaveBeenCalledWith('/p3/audit-runs/R1/evidence-requests','GET',undefined,expect.any(AbortSignal));
 await userEvent.click(screen.getByRole('link',{name:'Findings'}));await screen.findByText('Missing document');expect(screen.getAllByText(/RELATED/).length).toBeGreaterThan(0);
})

it('redirects old related-party links into the findings filter',async()=>{
 mount('/auditor/runs/R1/relationships?upload=REG2');await screen.findByLabelText('Finding category');expect(screen.getByLabelText('Finding category')).toHaveValue('related');expect(screen.queryByText('Missing document')).not.toBeInTheDocument();
})

it('clears old package details during loading, failure, and deselection',async()=>{
 let resolvePackage:(value:unknown)=>void=()=>{};
 session.api.json.mockImplementation(async(path:string)=>{if(path.startsWith('/ui/runs/R1/context'))return context;if(path==='/ui/runs')return {packages:[{run_id:'R1',upload_id:'REG2',package_id:'A'},{run_id:'R1',upload_id:'REG2',package_id:'B'},{run_id:'R1',upload_id:'REG1',package_id:'WRONG-REGISTER'}]};if(path==='/p5/packages/A')return {totals:{supported_confirmed_impact_inr:'100.00',confirmed_exceptions:1,open_reviews:2,unquantified_findings:3},receipt:{source_sha256:'original'},limitations:['Saved limitation'],content_digest:'digest-A'};if(path==='/p5/packages/B')return new Promise(resolve=>{resolvePackage=resolve});throw new Error('Unexpected API path: '+path)});
 mount('/auditor/runs/R1/workpapers?upload=REG2');await screen.findByRole('region',{name:'Saved packages'});expect(screen.queryByText('WRONG-REGISTER')).not.toBeInTheDocument()
 // Packages are listed newest first: A = "Package 2", B = "Package 1".
 await userEvent.click(screen.getByRole('button',{name:/Package 2/}));await screen.findByText('INR 100.00');await userEvent.click(screen.getByRole('button',{name:'Excel workpapers'}));expect(session.api.download).toHaveBeenCalledWith('/p5/packages/A/workpaper.xlsx','Pramaan_workpaper.xlsx')
 await userEvent.click(screen.getByRole('button',{name:/Package 1/}));expect(screen.queryByText('INR 100.00')).not.toBeInTheDocument();expect(screen.queryByRole('button',{name:'Excel workpapers'})).not.toBeInTheDocument()
 resolvePackage({totals:{supported_confirmed_impact_inr:'200.00',confirmed_exceptions:0,open_reviews:0,unquantified_findings:0},receipt:{},limitations:[],content_digest:'digest-B'});await screen.findByText('INR 200.00')
 expect(session.api.json.mock.calls.some(([path])=>path==='/p5/packages/')).toBe(false);
})

it('uses source-backed audit defaults and posts the values shown in the form',async()=>{
 session.api.json.mockImplementation(async(path:string,method:string,body:unknown)=>{if(path==='/ui/audit-setup')return {invoice_count:4,register_count:1,register_row_count:4,unreconciled_register_count:0,invoice_date_start:'2023-05-01',invoice_date_end:'2023-08-15',period_start:'2023-05-01',period_end:'2023-08-15'};if(path==='/p3/audit-runs'&&method==='POST')return {run_id:'R1',...body as object};if(path.startsWith('/ui/runs/R1/context'))return context;throw new Error('Unexpected API path: '+path)});
 mount('/auditor/runs/new');await screen.findByLabelText('Period start');expect(screen.getByLabelText('Period start')).toHaveValue('2023-05-01');expect(screen.getByLabelText('Period end')).toHaveValue('2023-08-15');expect((screen.getByLabelText('Fixed sampling seed (optional)') as HTMLInputElement).value).toBe('');await userEvent.click(screen.getByRole('button',{name:'Create audit run'}));await screen.findByRole('heading',{name:'Cedar Wholesale audit'});expect(session.api.json).toHaveBeenCalledWith('/p3/audit-runs','POST',{period_start:'2023-05-01',period_end:'2023-08-15',audit_name:'Revenue audit - May 2023 to Aug 2023',upload_id:null});
})

it('shows server field errors beside the field and sends an advanced seed only when chosen',async()=>{
 session.api.json.mockImplementation(async(path:string,method:string)=>{if(path==='/ui/audit-setup')return {invoice_count:4,register_count:0,register_row_count:0,unreconciled_register_count:0,unreadable_date_count:1,invoice_date_start:'2023-05-01',invoice_date_end:'2023-08-15',period_start:'2023-05-01',period_end:'2023-08-15'};if(path==='/p3/audit-runs'&&method==='POST')throw new ApiError(422,undefined,'Invalid request: sampling_seed: String should have at least 16 characters','invalid_input',[{field:'sampling_seed',message:'String should have at least 16 characters'}]);throw new Error('Unexpected API path: '+path)})
 mount('/auditor/runs/new');await screen.findByLabelText('Period start')
 expect(screen.getByText(/1 invoice record\(s\) have an unreadable date/)).toBeInTheDocument()
 await userEvent.click(screen.getByText('Advanced: re-perform a documented selection'))
 await userEvent.type(screen.getByLabelText('Fixed sampling seed (optional)'),'documented-seed-0001')
 await userEvent.click(screen.getByRole('button',{name:'Create audit run'}))
 expect(await screen.findByText('String should have at least 16 characters')).toBeInTheDocument()
 expect(session.api.json).toHaveBeenCalledWith('/p3/audit-runs','POST',expect.objectContaining({sampling_seed:'documented-seed-0001'}))
})
