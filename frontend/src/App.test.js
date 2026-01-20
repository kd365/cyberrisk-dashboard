import { render, screen } from '@testing-library/react';
import App from './App';

test('renders CyberRisk application', () => {
  render(<App />);
  const appElement = screen.getByText(/CyberRisk/i);
  expect(appElement).toBeInTheDocument();
});
