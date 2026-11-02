import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { Dialog } from './dialog';

function Nested() {
  const [outer, setOuter] = useState(true);
  const [inner, setInner] = useState(false);
  return (
    <Dialog open={outer} onClose={() => setOuter(false)} title="Luar">
      <button type="button" onClick={() => setInner(true)}>
        Buka pratinjau
      </button>
      <Dialog open={inner} onClose={() => setInner(false)} title="Dalam">
        <p>isi dalam</p>
      </Dialog>
    </Dialog>
  );
}

it('Escape closes only the top-most dialog', async () => {
  const user = userEvent.setup();
  render(<Nested />);
  await user.click(screen.getByRole('button', { name: 'Buka pratinjau' }));
  expect(screen.getByRole('dialog', { name: 'Dalam' })).toBeInTheDocument();
  await user.keyboard('{Escape}');
  expect(screen.queryByRole('dialog', { name: 'Dalam' })).not.toBeInTheDocument();
  expect(screen.getByRole('dialog', { name: 'Luar' })).toBeInTheDocument();
  await user.keyboard('{Escape}');
  expect(screen.queryByRole('dialog', { name: 'Luar' })).not.toBeInTheDocument();
});
