Gem::Specification.new do |spec|
  spec.name          = 'openc3-cosmos-plutosdr'
  spec.version       = '0.1.0'
  spec.authors       = ['Pluto COSMOS Starter']
  spec.summary       = 'ADALM-PLUTO spectrum analyzer target for OpenC3 COSMOS'
  spec.description   = 'Configurable receive-only PlutoSDR spectrum telemetry and controls'
  spec.files         = Dir.glob('plugin.txt') + Dir.glob('targets/**/*').select { |f| File.file?(f) }
  spec.require_paths = ['lib']
end
