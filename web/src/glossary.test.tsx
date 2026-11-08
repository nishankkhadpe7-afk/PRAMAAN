import {render,screen,fireEvent,act} from '@testing-library/react'
import {MemoryRouter} from 'react-router-dom'
import {describe,it,expect,beforeEach} from 'vitest'
import {GLOSSARY,GettingStarted,HelpContent,Term,eventLabel,sentence,termForLabel} from './glossary'

describe('glossary hints',()=>{
  it('keeps the label text unchanged and explains the word on demand',()=>{
    render(<p><Term k="seed">Seed</Term></p>)
    expect(screen.getByText('Seed',{exact:true})).toBeInTheDocument()
    const help=screen.getByRole('button',{name:'What does “Seed” mean?'})
    expect(help).toHaveAttribute('aria-expanded','false')
    fireEvent.click(help)
    expect(help).toHaveAttribute('aria-expanded','true')
    expect(screen.getByRole('note')).toHaveTextContent(GLOSSARY.seed.meaning)
    fireEvent.keyDown(help,{key:'Escape'})
    expect(screen.queryByRole('note')).not.toBeInTheDocument()
  })
  it('maps visible labels and event codes to plain language',()=>{
    expect(termForLabel('Population')).toBe('population')
    expect(termForLabel('population_projection')).toBe('population_projection')
    expect(termForLabel('Business invoices')).toBeUndefined()
    expect(eventLabel('register_imported')).toBe('Sales register uploaded')
    expect(eventLabel('some_new_event')).toBe('Some new event')
    expect(sentence('evaluated_for_selected_samples')).toBe('Evaluated for selected samples')
  })
})

describe('first-visit guide',()=>{
  beforeEach(()=>localStorage.clear())
  it('can be dismissed, stays dismissed, and comes back from Help',()=>{
    const view=render(<MemoryRouter><GettingStarted role="client"/></MemoryRouter>)
    expect(screen.getByRole('heading',{name:'Getting started'})).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button',{name:'Hide the getting-started guide'}))
    expect(screen.queryByRole('heading',{name:'Getting started'})).not.toBeInTheDocument()
    view.unmount()
    render(<MemoryRouter><GettingStarted role="client"/><HelpContent role="client" onShowGuide={()=>{}}/></MemoryRouter>)
    expect(screen.queryByRole('heading',{name:'Getting started'})).not.toBeInTheDocument()
    act(()=>{fireEvent.click(screen.getByRole('button',{name:'Show the guide on the overview page'}))})
    expect(screen.getByRole('heading',{name:'Getting started'})).toBeInTheDocument()
  })
})
