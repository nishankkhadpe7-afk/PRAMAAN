import {render,screen} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {it,expect,vi} from 'vitest'
import {Table} from './components'
it('opens a clickable row exactly once when its link button is used (F3)',async()=>{const onRow=vi.fn();render(<Table rows={[{invoice_id:'I-1',bill_no:'B-1'}]} columns={[{label:'Bill',key:'bill_no'}]} onRow={onRow}/>);await userEvent.click(screen.getByRole('button',{name:/B-1/}));expect(onRow).toHaveBeenCalledTimes(1);await userEvent.click(screen.getByRole('row',{name:/B-1/}));expect(onRow).toHaveBeenCalledTimes(2)})
import {useState} from 'react'
import {Drawer} from './components'
function DrawerHost(){const [open,setOpen]=useState(false);return <><button onClick={()=>setOpen(true)}>Open details</button>{open&&<Drawer title="Details" onClose={()=>setOpen(false)}><button>First</button><button>Last</button></Drawer>}</>}
it('traps focus in the drawer and returns it to the opener (F7)',async()=>{render(<DrawerHost/>);const opener=screen.getByRole('button',{name:'Open details'});await userEvent.click(opener);expect(screen.getByRole('dialog')).toBeInTheDocument();expect(screen.getByLabelText('Close')).toHaveFocus();await userEvent.tab();await userEvent.tab();expect(screen.getByRole('button',{name:'Last'})).toHaveFocus();await userEvent.tab();expect(screen.getByLabelText('Close')).toHaveFocus();await userEvent.keyboard('{Escape}');expect(screen.queryByRole('dialog')).not.toBeInTheDocument();expect(opener).toHaveFocus()})
