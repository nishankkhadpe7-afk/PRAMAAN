import {render,screen} from '@testing-library/react'
import {MemoryRouter} from 'react-router-dom'
import {describe,it,expect} from 'vitest'
import {DocumentRead,ImportResult} from './client'

const wrap=(ui:React.ReactElement)=>render(<MemoryRouter>{ui}</MemoryRouter>)

describe('import reports',()=>{
  it('shows Tally counts and keeps rejected vouchers apart from skipped ones',()=>{
    wrap(<ImportResult result={{upload_id:'REG-1',row_count:2,source_format:'tally_xml',vouchers_seen:5,skipped_vouchers:2,rejected_vouchers:1,warning_count:1,
      skipped:[{voucher:'RCPT/001',reason:'not a sales voucher (Receipt)'}],rejected:[{voucher:'TLY/002',reason:"unreadable date 'bad'"}],warnings:[{voucher:'TLY/001',reason:'buyer GSTIN: check digit does not match'}]}}/>)
    const summary=screen.getByLabelText('Import summary')
    expect(summary).toHaveTextContent('2imported')
    expect(summary).toHaveTextContent('1rejected')
    expect(screen.getByText('1 sales voucher rejected — see why')).toBeInTheDocument()
    expect(screen.getByText('1 warning on imported rows')).toBeInTheDocument()
    expect(screen.getByText('1 voucher skipped — see why')).toBeInTheDocument()
  })
  it('explains a bank balance that does not add up and rows already imported',()=>{
    wrap(<ImportResult result={{statement_id:'BANK-1',row_count:4,source_format:'pdf',unread_lines:0,overlapping_rows:1,overlaps_statements:['BANK-0'],repeated_rows:[],
      balance_check:{status:'inconsistent',checked:4,mismatches:[{row_no:2,expected:'323000.00',printed:'324000.00'}]}}}/>)
    expect(screen.getByText(/does not add up on 1 row\./)).toBeInTheDocument()
    expect(screen.getByText(/already imported from BANK-0/)).toBeInTheDocument()
    expect(screen.queryByText(/mismatches/)).not.toBeInTheDocument()
  })
  it('says when an invoice reading is ambiguous or its tax does not add up',()=>{
    wrap(<DocumentRead read={{invoice_number:null,invoice_date:'2025-04-12',total_cents:11800000,ambiguous:{invoice_number:['A','B']},arithmetic:{status:'inconsistent',difference:'-18000.00'},warnings:[]}}/>)
    expect(screen.getByText(/two different values printed for invoice number/)).toBeInTheDocument()
    expect(screen.getByText(/tax does not add up/)).toBeInTheDocument()
  })
})
